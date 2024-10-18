import nltk
import os

nltk_data_dir = '/home/runner/nltk_data'
os.makedirs(nltk_data_dir, exist_ok=True)

nltk_packages = ['punkt', 'stopwords', 'averaged_perceptron_tagger', 'maxent_ne_chunker', 'words']

for package in nltk_packages:
    nltk.download(package, download_dir=nltk_data_dir, quiet=True)

print("NLTK data download complete.")
