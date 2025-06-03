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
VALID_STATE_COLUMN_NAMES = ['state', 'states']

# Dictionary of US state abbreviations
STATES = {
    'AL': 'Alabama',
    'AK': 'Alaska',
    'AZ': 'Arizona',
    'AR': 'Arkansas',
    'CA': 'California',
    'CO': 'Colorado',
    'CT': 'Connecticut',
    'DE': 'Delaware',
    'FL': 'Florida',
    'GA': 'Georgia',
    'HI': 'Hawaii',
    'ID': 'Idaho',
    'IL': 'Illinois',
    'IN': 'Indiana',
    'IA': 'Iowa',
    'KS': 'Kansas',
    'KY': 'Kentucky',
    'LA': 'Louisiana',
    'ME': 'Maine',
    'MD': 'Maryland',
    'MA': 'Massachusetts',
    'MI': 'Michigan',
    'MN': 'Minnesota',
    'MS': 'Mississippi',
    'MO': 'Missouri',
    'MT': 'Montana',
    'NE': 'Nebraska',
    'NV': 'Nevada',
    'NH': 'New Hampshire',
    'NJ': 'New Jersey',
    'NM': 'New Mexico',
    'NY': 'New York',
    'NC': 'North Carolina',
    'ND': 'North Dakota',
    'OH': 'Ohio',
    'OK': 'Oklahoma',
    'OR': 'Oregon',
    'PA': 'Pennsylvania',
    'RI': 'Rhode Island',
    'SC': 'South Carolina',
    'SD': 'South Dakota',
    'TN': 'Tennessee',
    'TX': 'Texas',
    'UT': 'Utah',
    'VT': 'Vermont',
    'VA': 'Virginia',
    'WA': 'Washington',
    'WV': 'West Virginia',
    'WI': 'Wisconsin',
    'WY': 'Wyoming',
    'DC': 'District of Columbia'
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def find_column(df, valid_names):
    """Find a column name regardless of case"""
    for col in df.columns:
        if col.lower() in valid_names:
            return col
    return None

def find_address_column(df):
    """Find the address column name regardless of case"""
    return find_column(df, VALID_COLUMN_NAMES)

def find_state_column(df):
    """Find the state column name regardless of case"""
    return find_column(df, VALID_STATE_COLUMN_NAMES)

def standardize_state(state):
    """Convert state abbreviation or name to full state name"""
    if pd.isna(state) or not isinstance(state, str):
        return None
    
    state = state.strip().upper()
    
    # If it's already a full state name, return it properly capitalized
    for full_name in STATES.values():
        if state == full_name.upper():
            return full_name
    
    # If it's an abbreviation, convert to full name
    return STATES.get(state, state)  # Return original if not found

def standardize_address(address):
    # Remove leading/trailing spaces
    address = address.strip()
    
    # Dictionary of compound directional abbreviations (process these first)
    directionals = {
        r'\bnw\b\.?': 'northwest',
        r'\bne\b\.?': 'northeast',
        r'\bsw\b\.?': 'southwest',
        r'\bse\b\.?': 'southeast'
    }
    
    # Replace compound directionals first
    for abbr, full in directionals.items():
        address = re.sub(abbr, full, address, flags=re.IGNORECASE)
    
    # Dictionary of common abbreviations
    abbreviations = {
        r'\bcor\b\.?': 'corner',
        r'\bst\b\.?': 'street',
        r'\b(?:ave?|avn)\b\.?': 'avenue',  # matches ave, av, and avn
        r'\brd\b\.?': 'road',
        r'\bblvd\b\.?': 'boulevard',
        r'\bln\b\.?': 'lane',
        r'\bdr\b\.?': 'drive',
        r'\bapt\b\.?': 'apartment',
        r'\bfl\b\.?': 'floor',
        r'\brt\b\.?': 'route',
        r'\bhwy\b\.?': 'highway',
        r'\bp(?:k?wy|rkw)\b\.?': 'parkway',  # matches pkwy, prkw, pwy
        r'\bsq\b\.?': 'square',
        r'\bpl\b\.?': 'place',
        r'\bter\b\.?': 'terrace',
        r'\bcir\b\.?': 'circle',
        r'\bct\b\.?': 'court',
        r'\bexpy\b\.?': 'expressway',
        r'\bfwy\b\.?': 'freeway',
        r'\bste\b\.?': 'suite',
        r'\bn\b\.?': 'north',
        r'\bs\b\.?': 'south',
        r'\be\b\.?': 'east',
        r'\bw\b\.?': 'west',
        r'\bno\b\.?': 'number',
        r'\b#\b': 'number',
        r'\bext\b\.?': 'extension',
        r'\bse\b\.?': 'section'
    }
    
    # Replace other abbreviations
    for abbr, full in abbreviations.items():
        address = re.sub(abbr, full, address, flags=re.IGNORECASE)
    
    return address

def get_maps_search_url(address, state=None):
    """Generate a Google Maps search URL for the address"""
    base_url = "https://www.google.com/maps/search/"
    full_address = f"{address}, {state}" if state else address
    encoded_address = urllib.parse.quote(full_address)
    return f"{base_url}{encoded_address}"

def process_address(address, state=None):
    if pd.isna(address) or not isinstance(address, str):
        return None, None, None, False
    
    standardized_address = standardize_address(address)
    standardized_state = standardize_state(state) if state else None
    maps_url = get_maps_search_url(standardized_address, standardized_state)
    
    return standardized_address, standardized_state, maps_url, True

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
        
        # Find the address and state columns
        address_column = find_address_column(df)
        state_column = find_state_column(df)
        
        if not address_column:
            return jsonify({'error': 'No column named "Address" or "Addresses" found in the file'}), 400
        
        # Create new columns for the processed data
        df['Standardized_Address'] = None
        df['Standardized_State'] = None
        df['Maps_URL'] = None
        df['Address_Updated'] = False
        
        # Process each address
        for idx in df.index:
            if pd.notna(df.at[idx, address_column]):
                state_value = df.at[idx, state_column] if state_column else None
                standardized_addr, standardized_state, maps_url, was_updated = process_address(
                    df.at[idx, address_column],
                    state_value
                )
                if was_updated:
                    df.at[idx, 'Standardized_Address'] = standardized_addr
                    df.at[idx, 'Standardized_State'] = standardized_state
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