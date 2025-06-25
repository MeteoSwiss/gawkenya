import argparse
from pathlib import Path
import logging
from toolbox.utils import setup_logging
from toolbox.organize_files import organize_files_by_date


def main():
    """
    Example call:
    python organize_files.py /product_data/data/pay/Kenya/MKN/archive/g2401 /proj/pay/repos_pay/GAW_Kenya/MKN/g2401 --logfile organize_files.log --level DEBUG
    """
    parser = argparse.ArgumentParser(
        description="Organize files by datetime stamp in filenames. Mainly useful for archiving."
    )
    parser.add_argument(
        "--source", type=str, default="/product_data/data/pay/Kenya/MKN/archive/ne300", help="Root source directory to scan for files."
    )
    parser.add_argument(
        "--target", type=str, default="/proj/pay/repos_pay/GAW_Kenya/MKN/ne300", help="Target directory to organize files into."
    )
    parser.add_argument(
        "--logfile", type=str, default="organize_files_issues.log", help="Log file name (default: organize_files_issues.log)"
    )
    parser.add_argument(
        "--level", type=str, choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="DEBUG",
        help="Logging level (default: INFO)"
    )

    args = parser.parse_args()
    log_path = Path(args.source) / args.logfile
    logger = setup_logging(log_path, level_console=args.level, level_file="WARNING")

    logger.info(f"Starting file organization from {args.source} to {args.target}")
    organize_files_by_date(Path(args.source), Path(args.target), logger)
    logger.info("File organization completed.")


if __name__ == "__main__":
    main()

