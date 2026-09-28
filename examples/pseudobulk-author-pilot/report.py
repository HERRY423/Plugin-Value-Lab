"""Print a review summary of every local raw journal, including interrupted attempts."""
from pathlib import Path
import json
import argparse
from observe import summarize_folder

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Review all local author attempts and complete burden; never invent human observations')
    parser.add_argument('packet', nargs='?', type=Path, default=Path(__file__).resolve().parents[2] / 'work/author-pilot')
    args = parser.parse_args()
    print(json.dumps(summarize_folder(args.packet), ensure_ascii=True, indent=2, allow_nan=False))
