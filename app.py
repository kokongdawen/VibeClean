import os
from flask import Flask, request, render_template, send_file, jsonify
import pandas as pd
import re
from werkzeug.utils import secure_filename
import openpyxl
import urllib.parse
import tempfile
from pathlib import Path

app = Flask(__name__)

# Use temp directory for file uploads in serverless environment
UPLOAD_FOLDER = tempfile.gettempdir()
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Add some basic security headers
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

ALLOWED_EXTENSIONS = {'xls', 'xlsx', 'csv'}
VALID_COLUMN_NAMES = ['address', 'addresses']

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def find_address_column(df):
    """Find the address column name regardless of case"""
    for col in df.columns:
        if col.lower() in VALID_COLUMN_NAMES:
            return col
    return None

def save_file(df, filename, format_type):
    """Save file in specified format with optional Excel formatting"""
    base_filename = os.path.splitext(filename)[0]
    if format_type == 'csv':
        output_filename = f"updated_{base_filename}.csv"
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
        df.to_csv(output_path, index=False)
    else:  # xlsx
        output_filename = f"updated_{base_filename}.xlsx"
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
        writer = pd.ExcelWriter(output_path, engine='openpyxl')
        df.to_excel(writer, index=False)
        
        # Add Excel formatting
        workbook = writer.book
        worksheet = writer.sheets['Sheet1']
        
        # Add green fill for updated rows
        green_fill = openpyxl.styles.PatternFill(start_color='90EE90',
                                                end_color='90EE90',
                                                fill_type='solid')
        
        # Apply conditional formatting
        for idx, row in enumerate(df.itertuples(), start=2):
            if row.Address_Updated:
                for col in range(1, len(df.columns) + 1):
                    worksheet.cell(row=idx, column=col).fill = green_fill
        
        writer.close()
    
    return output_filename, output_path

def standardize_address(address):
    # Remove leading/trailing spaces
    address = address.strip()
    
    # Dictionary of common abbreviations
    abbreviations = {
        r'\bcor\b\.?': 'corner',
        r'\bst\b\.?': 'street',
        r'\bave\b\.?': 'avenue',
        r'\brd\b\.?': 'road',
        r'\bblvd\b\.?': 'boulevard',
        r'\bln\b\.?': 'lane',
        r'\bdr\b\.?': 'drive',
        r'\bapt\b\.?': 'apartment',
        r'\bfl\b\.?': 'floor'
    }
    
    # Replace abbreviations
    for abbr, full in abbreviations.items():
        address = re.sub(abbr, full, address, flags=re.IGNORECASE)
    
    return address

def get_maps_search_url(address):
    """Generate a Google Maps search URL for the address"""
    base_url = "https://www.google.com/maps/search/"
    encoded_address = urllib.parse.quote(address)
    return f"{base_url}{encoded_address}"

def process_address(address):
    if pd.isna(address) or not isinstance(address, str):
        return None, None, False
    
    standardized_address = standardize_address(address)
    maps_url = get_maps_search_url(standardized_address)
    
    return standardized_address, maps_url, True

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type'}), 400
    
    try:
        # Secure the filename
        filename = secure_filename(file.filename)
        
        # Read the file based on its extension
        file_extension = filename.rsplit('.', 1)[1].lower()
        if file_extension == 'csv':
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
        
        # Find the address column
        address_column = find_address_column(df)
        if not address_column:
            return jsonify({'error': 'No column named "Address" or "Addresses" found in the file'}), 400
        
        # Create new columns for the processed data
        df['Standardized_Address'] = None
        df['Maps_URL'] = None
        df['Address_Updated'] = False
        
        # Process each address
        for idx in df.index:
            if pd.notna(df.at[idx, address_column]):
                standardized, maps_url, was_updated = process_address(df.at[idx, address_column])
                if was_updated:
                    df.at[idx, 'Standardized_Address'] = standardized
                    df.at[idx, 'Maps_URL'] = maps_url
                    df.at[idx, 'Address_Updated'] = True
        
        # Save both CSV and Excel versions
        csv_filename, csv_path = save_file(df, filename, 'csv')
        xlsx_filename, xlsx_path = save_file(df, filename, 'xlsx')
        
        return jsonify({
            'success': True,
            'csv_filename': csv_filename,
            'xlsx_filename': xlsx_filename
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<filename>')
def download_file(filename):
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
            
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# For local development
if __name__ == '__main__':
    # Only enable debug mode in development
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(debug=debug_mode) 