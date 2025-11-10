import csv, os, time, requests
from pathlib import Path
from urllib.parse import urlparse, unquote

UA = {"User-Agent": "TPA-harvester/1.0 (+planning use)"}
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

def sanitize_filename(s: str, max_len: int = 200) -> str:
    """Convert string to safe filename"""
    # Remove/replace unsafe characters
    unsafe = '<>:"/\\|?*'
    for char in unsafe:
        s = s.replace(char, '_')
    # Remove leading/trailing spaces and dots
    s = s.strip('. ')
    # Limit length
    if len(s) > max_len:
        s = s[:max_len]
    return s or "unnamed"

def get_filename_from_url(url: str, doc_ref: str, doc_name: str, file_kind: str) -> str:
    """Generate filename from URL or metadata"""
    # Try to get filename from URL
    path = urlparse(url).path
    url_filename = unquote(os.path.basename(path))
    
    # If URL has a good filename with extension, use it
    if url_filename and '.' in url_filename:
        name, ext = os.path.splitext(url_filename)
        name = sanitize_filename(name, max_len=150)
        return f"{doc_ref}_{name}{ext}"
    
    # Otherwise construct from metadata
    base = sanitize_filename(f"{doc_ref}_{doc_name}", max_len=150)
    
    # Add appropriate extension
    ext_map = {
        "pdf": ".pdf",
        "html": ".html",
        "doc": ".doc",
        "image": ".jpg",
    }
    ext = ext_map.get(file_kind, ".bin")
    
    return f"{base}{ext}"

def download_file(url: str, filepath: Path, timeout: int = 120) -> tuple[bool, str]:
    """Download file from URL to filepath. Returns (success, error_message)."""
    if not url:
        return False, "No URL provided"
    
    try:
        print(f"  Downloading: {url[:80]}...")
        r = requests.get(url, headers=UA, timeout=timeout, stream=True)
        r.raise_for_status()
        
        # Write in chunks to handle large files
        with open(filepath, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        
        file_size = filepath.stat().st_size
        print(f"  ✓ Saved: {filepath.name} ({file_size:,} bytes)")
        return True, ""
        
    except requests.RequestException as e:
        error_msg = f"{type(e).__name__}: {str(e)[:100]}"
        print(f"  ✗ Failed: {error_msg}")
        # Remove partial download
        if filepath.exists():
            filepath.unlink()
        return False, error_msg

def download_documents(csv_path: str = "local_plan_documents_clean.csv", 
                       max_downloads: int = None,
                       skip_existing: bool = True,
                       file_kinds: list = None,
                       log_failures: bool = True):
    """
    Download documents from CSV.
    
    Args:
        csv_path: Path to the CSV file
        max_downloads: Maximum number of files to download (None = all)
        skip_existing: Skip files that already exist
        file_kinds: List of file_kind values to download (None = all, e.g., ["pdf"])
        log_failures: Write failed downloads to a log file
    """
    
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        return
    
    stats = {
        "total": 0,
        "skipped_no_url": 0,
        "skipped_exists": 0,
        "skipped_kind": 0,
        "downloaded": 0,
        "failed": 0,
    }
    
    failed_downloads = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            stats["total"] += 1
            
            # Get the file URL (prefer final_url, fallback to landing_url)
            url = row.get("final_url", "").strip()
            if not url:
                url = row.get("landing_url", "").strip()
            
            if not url:
                stats["skipped_no_url"] += 1
                continue
            
            # Filter by file kind if specified
            file_kind = row.get("file_kind", "")
            if file_kinds and file_kind not in file_kinds:
                stats["skipped_kind"] += 1
                continue
            
            # Generate filename
            doc_ref = row.get("doc_reference", "unknown")
            doc_name = row.get("doc_name", "document")
            local_plan = row.get("local_plan", "")
            
            # Create subdirectory for each local plan
            if local_plan:
                plan_dir = DOWNLOAD_DIR / sanitize_filename(local_plan)
                plan_dir.mkdir(exist_ok=True)
            else:
                plan_dir = DOWNLOAD_DIR / "uncategorized"
                plan_dir.mkdir(exist_ok=True)
            
            filename = get_filename_from_url(url, doc_ref, doc_name, file_kind)
            filepath = plan_dir / filename
            
            # Skip if already exists
            if skip_existing and filepath.exists():
                print(f"[{stats['total']}] Skipping existing: {filepath.name}")
                stats["skipped_exists"] += 1
                continue
            
            # Download
            print(f"[{stats['total']}] {doc_ref}: {doc_name[:60]}")
            success, error_msg = download_file(url, filepath)
            if success:
                stats["downloaded"] += 1
            else:
                stats["failed"] += 1
                failed_downloads.append({
                    "doc_reference": doc_ref,
                    "doc_name": doc_name,
                    "url": url,
                    "error": error_msg,
                    "lpa_curie": row.get("lpa_curie", ""),
                    "lpa_name": row.get("lpa_name", ""),
                    "local_plan": local_plan,
                })
            
            # Check if we've hit the download limit
            if max_downloads and stats["downloaded"] >= max_downloads:
                print(f"\nReached download limit of {max_downloads}")
                break
            
            # Rate limiting
            time.sleep(0.5)
    
    # Print summary
    print("\n" + "="*60)
    print("Download Summary:")
    print(f"  Total rows in CSV: {stats['total']}")
    print(f"  Skipped (no URL): {stats['skipped_no_url']}")
    print(f"  Skipped (file kind filter): {stats['skipped_kind']}")
    print(f"  Skipped (already exists): {stats['skipped_exists']}")
    print(f"  Successfully downloaded: {stats['downloaded']}")
    print(f"  Failed downloads: {stats['failed']}")
    print(f"\nFiles saved to: {DOWNLOAD_DIR.absolute()}")
    
    # Write failures log
    if log_failures and failed_downloads:
        failures_log = "download_failures.csv"
        with open(failures_log, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=failed_downloads[0].keys())
            writer.writeheader()
            writer.writerows(failed_downloads)
        print(f"Failed downloads logged to: {failures_log}")
    
    print("="*60)
    
    return stats, failed_downloads

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Download planning documents from CSV")
    parser.add_argument("--csv", default="local_plan_documents_clean.csv",
                       help="Path to CSV file (default: local_plan_documents_clean.csv)")
    parser.add_argument("--max", type=int, default=None,
                       help="Maximum number of files to download")
    parser.add_argument("--no-skip-existing", action="store_true",
                       help="Re-download files that already exist")
    parser.add_argument("--kinds", nargs="+", 
                       help="Only download specific file kinds (e.g., --kinds pdf)")
    
    args = parser.parse_args()
    
    download_documents(
        csv_path=args.csv,
        max_downloads=args.max,
        skip_existing=not args.no_skip_existing,
        file_kinds=args.kinds
    )
