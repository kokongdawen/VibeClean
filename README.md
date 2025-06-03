# Address Checker Web App

A web application that validates and standardizes addresses in Excel files using Google Maps API.

## Features

- Upload XLS/XLSX files containing addresses
- Validate addresses using Google Maps API
- Standardize address abbreviations (e.g., "st." to "street")
- Highlight modified addresses in green
- Download updated XLSX file
- Modern and user-friendly interface
- Drag and drop file upload support

## Requirements

- Python 3.7+
- Flask
- pandas
- openpyxl
- xlrd
- googlemaps
- python-dotenv

## Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd address-checker
```

2. Create a virtual environment and activate it:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install the required packages:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root and add your Google Maps API key:
```
GOOGLE_MAPS_API_KEY=your_api_key_here
```

5. Run the application:
```bash
python app.py
```

The application will be available at `http://localhost:5000`

## Usage

1. Open the application in your web browser
2. Upload an Excel file containing addresses (must have an "Address" column)
3. Wait for the processing to complete
4. Download the updated file

## Excel File Format

The input Excel file should have a column named "Address" containing the addresses to validate and standardize. The application will:

- Remove leading/trailing spaces
- Standardize common abbreviations
- Validate addresses using Google Maps
- Highlight modified addresses in green
- Keep original addresses if no close match is found

## Notes

- The application will only modify addresses when it finds a close match from Google Maps
- Addresses that cannot be found or have significantly different suggestions will be left unchanged
- The output file will be in XLSX format, regardless of the input format (XLS or XLSX)
- Modified rows will be highlighted in green for easy identification

## Security

- The application accepts only XLS and XLSX files
- Maximum file size is limited to 16MB
- Processed files are stored temporarily and cleaned up after download 