# Specification for the command-line data extractor

## Overview

The command-line data extractor is a Python command-line tool that serves to extract the monthly mobile data volume used per app from screenshots taken on an iPhone and store it in a SQLite database. The evaluation of the extracted data will be performed by another tool which will be developed later.

## Detailed Specification

* Use `argparse` to get the input folder containing the screenshots.
* Iterate over each image file in the input folder.
  * To extract the month use the image's metadata (but not the file timestamp) and take the month before the image is taken, e.g. when it is taken on 1st of February 2026 the month is January 2026. You can use the **Pillow** module to access the image metadata.
  * To extract the app names and data volumes use an OCR tool. **GNU Tesseract** is available on the command-line, but if there is a Python module for that it is also okay to use it.
  * There are two cases where to find the data volume on the screenshots:
    1. In the screenshot there is a list of apps with each used mobile data volume below the app name.
    2. In the screenshot there is a list of system services (header "Systemdienste") with each used mobile data volume right of the app name.
  * Both (apps and system services) can be treated the same way. Note, that each numerical value of the app's data volume is followed by a unit (GB, MB, KB), so that before storing the app's data volume in the database it is required to convert it to a uniform and consistent unit. Use 1024 as factor between KB and MB as well as between MB and GB. When the data volume is just a number "bytes" (i.e. <1 KB) the entry can be ignored.
  * If the same app entry is contained in two or more screenshot for the same month ignore the surplus entries.
* Put (at least) the following data in the database: year, month (numeric), app name, data volume.
* If the database file does not exist, create a new one.
* Report progress on stdout.

## Overall Guidelines

* The code should be keept modular.
* The extractor should be located in the `extractor` folder of the repository.
* Use ```uv add``` to add Python dependencies (modules) when required.
* Edit/create ```AGENTS.md``` accordingly, i.e., when using Python dependencies.

## Required Quality Assurance

A test set was prepared in folder `extractor/test`. It contains the data volumes to be extracted from the screenshots in its "input" folder (for January 2026) and the expected data extracted in the file ```data.csv```.

Use Python's `unittest` module for implementing the tests.
