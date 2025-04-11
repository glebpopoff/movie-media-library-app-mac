import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageTk
import io
import subprocess
import os
import json
from urllib.parse import quote_plus
from pathlib import Path
import threading
from queue import Queue
import time

class MovieLibrary(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Movie Library")
        self.geometry("1024x768")
        
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        
        # Main tab
        self.main_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.main_tab, text="Movies")
        
        # Debug tab
        self.debug_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.debug_tab, text="Debug")
        
        # Debug log
        self.debug_frame = ttk.Frame(self.debug_tab)
        self.debug_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.debug_text = tk.Text(self.debug_frame, wrap=tk.WORD, height=20)
        self.debug_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        debug_scrollbar = ttk.Scrollbar(self.debug_frame, command=self.debug_text.yview)
        debug_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.debug_text.configure(yscrollcommand=debug_scrollbar.set)
        
        # Clear debug button
        clear_button = ttk.Button(self.debug_tab, text="Clear Log", 
                                command=lambda: self.debug_text.delete(1.0, tk.END))
        clear_button.pack(pady=5)
        
        # Load configuration
        self.config_path = Path("config.json")
        self.load_config()
        
        # Initialize movie data
        self.movies = {}
        self.movie_widgets = []
        self.movie_queue = Queue()
        self.processing = False
        
        # Configure grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Settings frame
        settings_frame = ttk.Frame(self.main_tab)
        settings_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(settings_frame, text="Movie Directory:").pack(side=tk.LEFT, padx=(0, 5))
        self.dir_var = tk.StringVar(value=self.config.get("movie_directory", ""))
        dir_entry = ttk.Entry(settings_frame, textvariable=self.dir_var, width=50)
        dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        browse_button = ttk.Button(settings_frame, text="Browse", command=self.browse_directory)
        browse_button.pack(side=tk.LEFT, padx=(0, 5))
        
        scan_button = ttk.Button(settings_frame, text="Scan Movies", command=self.scan_movies)
        scan_button.pack(side=tk.LEFT)

        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress = ttk.Progressbar(settings_frame, variable=self.progress_var, maximum=100)
        self.progress.pack(side=tk.LEFT, padx=(5, 0), fill=tk.X, expand=True)

        # Main content frame with canvas for thumbnails
        self.content_frame = ttk.Frame(self.main_tab)
        self.content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(0, weight=1)

        # Create canvas with scrollbar
        self.canvas = tk.Canvas(self.content_frame)
        scrollbar = ttk.Scrollbar(self.content_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        # Frame for thumbnails inside canvas
        self.thumbnails_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.thumbnails_frame, anchor="nw")
        
        # Configure canvas scrolling
        self.thumbnails_frame.bind("<Configure>", self.on_frame_configure)
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        
        # Auto-load movies if directory exists
        if self.config.get("movie_directory"):
            directory = os.path.expanduser(self.config["movie_directory"])
            if os.path.exists(directory):
                self.log_debug(f"Auto-loading movies from {directory}")
                self.load_existing_movies(directory)

    def load_config(self):
        if self.config_path.exists():
            with open(self.config_path) as f:
                self.config = json.load(f)
        else:
            self.config = {"movie_directory": ""}
            self.save_config()
    
    def save_config(self):
        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=4)
    
    def browse_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.dir_var.set(directory)
            self.config["movie_directory"] = directory
            self.save_config()
    
    def load_cached_movie_info(self, movie_path):
        json_path = Path(movie_path).with_suffix('.json')
        if json_path.exists():
            try:
                with open(json_path, 'r') as f:
                    movie_info = json.load(f)
                    # Load thumbnail image
                    thumbnail_path = Path(movie_path).with_suffix('.jpg')
                    if thumbnail_path.exists():
                        img_data = Image.open(thumbnail_path)
                        movie_info['thumbnail'] = ImageTk.PhotoImage(img_data)
                        movie_info['path'] = movie_path
                        return movie_info
            except Exception as e:
                self.log_debug(f"Error loading cached info for {movie_path}: {e}")
        return None

    def save_movie_info(self, movie_path, movie_info):
        try:
            # Save JSON info
            json_path = Path(movie_path).with_suffix('.json')
            save_info = movie_info.copy()
            save_info.pop('thumbnail')  # Remove PIL image before saving
            with open(json_path, 'w') as f:
                json.dump(save_info, f, indent=4)

            # Save thumbnail
            if movie_info.get('thumbnail_url'):
                thumbnail_path = Path(movie_path).with_suffix('.jpg')
                headers = {'User-Agent': 'Mozilla/5.0'}
                response = requests.get(movie_info['thumbnail_url'], headers=headers)
                if response.status_code == 200:
                    with open(thumbnail_path, 'wb') as f:
                        f.write(response.content)
        except Exception as e:
            self.log_debug(f"Error saving movie info for {movie_path}: {e}")

    def scan_movies(self):
        directory = self.dir_var.get()
        if not directory:
            messagebox.showerror("Error", "Please select a movie directory first")
            return
        
        self.log_debug("Starting movie scan...")

        directory = os.path.expanduser(directory)
        if not os.path.exists(directory):
            messagebox.showerror("Error", f"Directory does not exist: {directory}")
            return

        # Save directory in config
        self.config["movie_directory"] = directory
        self.save_config()

        # Clear existing thumbnails
        for widget in self.movie_widgets:
            widget.destroy()
        self.movie_widgets.clear()
        self.movies.clear()

        # First load all existing movies
        self.load_existing_movies(directory)

        # Then start scanning for new ones
        self.progress_var.set(0)
        self.processing = True

        # Start scanning in a background thread
        thread = threading.Thread(target=self.scan_directory, args=(directory,))
        thread.daemon = True
        thread.start()

        # Start processing queue in another thread
        process_thread = threading.Thread(target=self.process_movie_queue)
        process_thread.daemon = True
        process_thread.start()

        # Start progress update
        self.update_progress()

    def load_existing_movies(self, directory):
        movie_extensions = {".mp4", ".mkv", ".avi", ".mov", ".wmv"}
        for root, _, files in os.walk(directory):
            for file in files:
                if Path(file).suffix.lower() in movie_extensions:
                    movie_path = os.path.join(root, file)
                    # Try to load cached info
                    movie_info = self.load_cached_movie_info(movie_path)
                    if movie_info:
                        self.movies[movie_path] = movie_info
                        self.add_thumbnail(movie_path)
    
    def log_debug(self, message):
        self.debug_text.insert(tk.END, f"{time.strftime('%H:%M:%S')}: {message}\n")
        self.debug_text.see(tk.END)
    
    def scan_directory(self, directory):
        try:
            movie_extensions = {".mp4", ".mkv", ".avi", ".mov", ".wmv"}
            total_files = 0
            
            for root, _, files in os.walk(directory):
                for file in files:
                    if Path(file).suffix.lower() in movie_extensions:
                        movie_path = os.path.join(root, file)
                        # Only process if we don't have cached info
                        if movie_path not in self.movies:
                            movie_name = Path(file).stem
                            self.movie_queue.put((movie_name, movie_path))
                            total_files += 1
                            self.log_debug(f"Found new movie: {movie_name}")
            
            # Add sentinel to mark end of scanning
            self.movie_queue.put((None, None))
            
        except Exception as e:
            error_msg = f"Error scanning directory: {str(e)}"
            self.log_debug(f"ERROR: {error_msg}")
            messagebox.showerror("Error", error_msg)
            self.processing = False

    def process_movie_queue(self):
        while self.processing:
            movie_name, movie_path = self.movie_queue.get()
            
            if movie_name is None:  # sentinel value
                self.log_debug("Finished processing all movies")
                self.processing = False
                break
            
            try:
                self.log_debug(f"Processing movie: {movie_name}")
                # Search IMDB
                search_url = f"https://www.imdb.com/find?q={quote_plus(movie_name)}&s=tt&ttype=ft"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Connection': 'keep-alive',
                }
                self.log_debug(f"Searching IMDB: {search_url}")
                response = requests.get(search_url, headers=headers)
                self.log_debug(f"IMDB response status: {response.status_code}")
                
                # Save response for debugging
                debug_file = f"imdb_search_{movie_name}.html"
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(response.text)
                self.log_debug(f"Saved IMDB response to {debug_file}")
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Debug HTML structure
                self.log_debug("Looking for movie results...")
                all_results = soup.select('.ipc-metadata-list-summary-item')
                self.log_debug(f"Found {len(all_results)} potential results")
                
                # Find first movie result
                movie_item = soup.select_one('.ipc-metadata-list-summary-item')
                if movie_item:
                    self.log_debug("Found movie on IMDB")
                    self.log_debug(f"Movie item HTML: {movie_item.prettify()}")
                    # Get movie details
                    title_elem = movie_item.select_one('.ipc-metadata-list-summary-item__t')
                    if title_elem:
                        title = title_elem.text.strip()
                        self.log_debug(f"Found title: {title}")
                        
                        # Get movie page URL
                        link = title_elem.get('href')
                        if link:
                            self.log_debug(f"Found movie link: {link}")
                            movie_url = f"https://www.imdb.com{link}"
                            self.log_debug(f"Fetching movie page: {movie_url}")
                            response = requests.get(movie_url, headers=headers)
                            self.log_debug(f"Movie page response status: {response.status_code}")
                            
                            # Save movie page for debugging
                            debug_file = f"imdb_movie_{movie_name}.html"
                            with open(debug_file, 'w', encoding='utf-8') as f:
                                f.write(response.text)
                            self.log_debug(f"Saved movie page to {debug_file}")
                            
                            movie_soup = BeautifulSoup(response.text, 'html.parser')
                            
                            # Get thumbnail
                            self.log_debug("Looking for poster image...")
                            img_elem = movie_soup.select_one('img.ipc-image')
                            if not img_elem:
                                img_elem = movie_soup.select_one('img[class*="poster"]')
                            
                            if img_elem:
                                self.log_debug(f"Found image element: {img_elem}")
                            
                            if img_elem and 'src' in img_elem.attrs:
                                img_url = img_elem['src']
                                self.log_debug(f"Found thumbnail URL: {img_url}")
                                img_response = requests.get(img_url, headers=headers)
                                img_data = Image.open(io.BytesIO(img_response.content))
                                img_data.thumbnail((200, 300))
                                self.log_debug("Successfully downloaded and processed thumbnail")
                                
                                # Get rating
                                rating_elem = movie_soup.select_one('span[data-testid="aggregate-rating__score"]')
                                rating = '0.0'
                                if rating_elem:
                                    rating = rating_elem.text.strip()
                                    # Convert to single decimal format if needed
                                    try:
                                        rating = f"{float(rating):.1f}"
                                    except ValueError:
                                        pass
                                    self.log_debug(f"Found rating: {rating}")
                                
                                # Get year
                                year_elem = movie_soup.select_one('a[href*="releaseinfo"]')
                                year = 'N/A'
                                if year_elem:
                                    year = year_elem.text.strip()
                                    self.log_debug(f"Found year: {year}")
                                
                                # Store movie data
                                movie_info = {
                                    'title': title,
                                    'thumbnail': ImageTk.PhotoImage(img_data),
                                    'thumbnail_url': img_url,  # Store URL for caching
                                    'path': movie_path,
                                    'rating': rating,
                                    'year': year
                                }
                                self.movies[movie_path] = movie_info
                                
                                # Cache the movie information
                                self.save_movie_info(movie_path, movie_info)
                                
                                # Add thumbnail to UI in main thread
                                self.after(0, self.add_thumbnail, movie_path)
                
            except Exception as e:
                error_msg = f"Error processing {movie_name}: {str(e)}"
                self.log_debug(f"ERROR: {error_msg}")
                print(error_msg)
            
            self.movie_queue.task_done()

    def add_thumbnail(self, movie_path):
        movie = self.movies[movie_path]
        
        # Create frame for movie
        frame = ttk.Frame(self.thumbnails_frame)
        frame.grid(row=len(self.movie_widgets) // 4, 
                  column=len(self.movie_widgets) % 4,
                  padx=5, pady=5)
        
        # Add thumbnail
        label = ttk.Label(frame, image=movie['thumbnail'])
        label.pack()
        
        # Add title with year
        title_text = f"{movie['title']} ({movie['year']})"
        title_label = ttk.Label(frame, text=title_text, wraplength=200)
        title_label.pack()
        
        # Add rating
        rating_text = f"★ {movie['rating']}"
        rating_label = ttk.Label(frame, text=rating_text, foreground='gold4')
        rating_label.pack()
        
        # Bind click event
        label.bind('<Button-1>', lambda e, path=movie_path: self.play_movie(path))
        
        self.movie_widgets.append(frame)
    
    def play_movie(self, movie_path):
        try:
            subprocess.Popen(['vlc', movie_path])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch VLC: {str(e)}")
    
    def on_frame_configure(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    
    def on_canvas_configure(self, event):
        # Update the width of the frame to fit the canvas
        self.canvas.itemconfig(self.canvas.find_withtag("all")[0],
                             width=event.width)
    
    def update_progress(self):
        if self.processing:
            # Calculate progress based on queue size
            total = self.movie_queue.qsize()
            if total > 0:
                progress = ((total - self.movie_queue.qsize()) / total) * 100
                self.progress_var.set(progress)
            self.after(100, self.update_progress)
        else:
            self.progress_var.set(100)

if __name__ == "__main__":
    app = MovieLibrary()
    app.mainloop()
