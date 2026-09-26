"""Print a review summary of every local raw journal, including interrupted attempts."""
from pathlib import Path
import json
from observe import summarize_folder

if __name__ == '__main__':
    print(json.dumps(summarize_folder(Path(__file__).resolve().parents[2] / 'work/author-pilot'), ensure_ascii=True, indent=2))
