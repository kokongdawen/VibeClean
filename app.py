import os
from flask import Flask, request, render_template, send_file, jsonify
import pandas as pd
import re
from werkzeug.utils import secure_filename
import openpyxl
import urllib.parse
import tempfile
from pathlib import Path
import html
import usaddress

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

ALLOWED_EXTENSIONS = {'xls', 'xlsx', 'csv', 'txt'}
VALID_COLUMN_NAMES = ['address', 'addresses']
VALID_STATE_COLUMN_NAMES = ['state', 'states']
VALID_CITY_COLUMN_NAMES = ['city', 'cities']
VALID_ZIP_COLUMN_NAMES = ['zip', 'zips', 'zip_code', 'zip_codes', 'zipcode', 'zipcodes']

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

def find_city_column(df):
    """Find the city column name regardless of case"""
    return find_column(df, VALID_CITY_COLUMN_NAMES)

def find_zip_column(df):
    """Find the ZIP code column name regardless of case"""
    return find_column(df, VALID_ZIP_COLUMN_NAMES)

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

def apply_apa_title_case(text):
    """Apply APA style title case formatting"""
    if pd.isna(text) or not isinstance(text, str):
        return text
        
    # Words that should not be capitalized unless they are the first word
    lowercase_words = {
        'a', 'an', 'the',  # Articles
        'and', 'but', 'or', 'for', 'nor',  # Coordinating conjunctions
        'in', 'on', 'at', 'by', 'to', 'of',  # Short prepositions
        'via', 'the'
    }
    
    # Split the text into words
    words = text.split()
    if not words:
        return text
        
    # Process each word
    result = []
    for i, word in enumerate(words):
        # Always capitalize first word
        if i == 0:
            result.append(word.capitalize())
            continue
            
        # Check if word contains hyphen
        if '-' in word:
            # Capitalize each part after hyphen
            parts = word.split('-')
            capitalized_parts = [p.capitalize() for p in parts]
            result.append('-'.join(capitalized_parts))
            continue
            
        # Don't capitalize short words unless they're proper nouns
        if (word.lower() in lowercase_words and 
            len(word) < 4 and 
            not word.isupper()  # Don't lowercase potential abbreviations
        ):
            result.append(word.lower())
        else:
            result.append(word.capitalize())
    
    return ' '.join(result)

def standardize_address(address):
    # Remove leading/trailing spaces
    address = address.strip()
    
    # Dictionary of compound directional abbreviations (process these first)
    directionals = {
        r'\bnw\b\.?': 'Northwest',
        r'\bne\b\.?': 'Northeast',
        r'\bsw\b\.?': 'Southwest',
        r'\bse\b\.?': 'Southeast'
    }
    
    # Replace compound directionals first
    for abbr, full in directionals.items():
        address = re.sub(abbr, full, address, flags=re.IGNORECASE)
    
    # Dictionary of common abbreviations
    abbreviations = {
        r'\bcor\b\.?': 'Corner',
        r'\bst\b\.?': 'Street',
        r'\b(?:ave?|avn)\b\.?': 'Avenue',  # matches ave, av, and avn
        r'\brd\b\.?': 'Road',
        r'\bblvd\b\.?': 'Boulevard',
        r'\bln\b\.?': 'Lane',
        r'\bdr\b\.?': 'Drive',
        r'\bapt\b\.?': 'Apartment',
        r'\bfl\b\.?': 'Floor',
        r'\brt\b\.?': 'Route',
        r'\bhwy\b\.?': 'Highway',
        r'\bp(?:k?wy|rkw)\b\.?': 'Parkway',  # matches pkwy, prkw, pwy
        r'\bsq\b\.?': 'Square',
        r'\bpl\b\.?': 'Place',
        r'\bter\b\.?': 'Terrace',
        r'\bcir\b\.?': 'Circle',
        r'\bct\b\.?': 'Court',
        r'\bexpy\b\.?': 'Expressway',
        r'\bfwy\b\.?': 'Freeway',
        r'\bste\b\.?': 'Suite',
        r'\bn\b\.?': 'North',
        r'\bs\b\.?': 'South',
        r'\be\b\.?': 'East',
        r'\bw\b\.?': 'West',
        r'\bno\b\.?': 'Number',
        r'\b#\b': 'Number',
        r'\bext\b\.?': 'Extension',
        r'\bse\b\.?': 'Section'
    }
    
    # Clean the text first
    address = clean_text(address)
    
    # Replace abbreviations
    for abbr, full in abbreviations.items():
        address = re.sub(abbr, full, address, flags=re.IGNORECASE)
    
    # Parse address into components
    components = parse_address(address)
    
    if components:
        # Apply APA title case to each component
        for key in components:
            if components[key]:
                components[key] = apply_apa_title_case(components[key])
        
        # Reconstruct the address
        parts = []
        if components['street_number']:
            parts.append(components['street_number'])
        if components['street_name']:
            parts.append(components['street_name'])
        if components['city']:
            parts.append(components['city'])
        if components['state']:
            parts.append(components['state'])
        if components['zip_code']:
            parts.append(components['zip_code'])
        
        return ', '.join(parts)
    else:
        # If parsing fails, just apply APA title case to the whole address
        return apply_apa_title_case(address)

def get_maps_search_url(address, state=None):
    """Generate a Google Maps search URL for the address"""
    base_url = "https://www.google.com/maps/search/"
    full_address = f"{address}, {state}" if state else address
    encoded_address = urllib.parse.quote(full_address)
    return f"{base_url}{encoded_address}"

def standardize_zip(zip_code):
    """Standardize ZIP code format"""
    if pd.isna(zip_code) or not isinstance(zip_code, str):
        return None
    
    # Remove any non-digit characters
    zip_code = re.sub(r'\D', '', str(zip_code))
    
    # Return first 5 digits if available
    return zip_code[:5] if len(zip_code) >= 5 else None

def standardize_city(city):
    """Standardize city name format"""
    if pd.isna(city) or not isinstance(city, str):
        return None
    
    # Clean the text first
    city = clean_text(city)
    
    # Title case the city name
    return city.title()

def process_address(address, state=None, city=None, zip_code=None):
    if pd.isna(address) or not isinstance(address, str):
        return None, None, None, None, None, None, False
    
    # Clean and standardize the address and components
    standardized_address = standardize_address(address)
    standardized_state = standardize_state(state) if state else None
    standardized_city = standardize_city(city) if city else None
    standardized_zip = standardize_zip(zip_code) if zip_code else None
    
    # Parse the standardized address
    components = parse_address(standardized_address)
    
    # If we have manual components, override the parsed ones
    if components:
        if standardized_city:
            components['city'] = standardized_city
        if standardized_state:
            components['state'] = standardized_state
        if standardized_zip:
            components['zip_code'] = standardized_zip
    
    # Generate Maps URL
    maps_url = get_maps_search_url(standardized_address, standardized_state)
    
    return standardized_address, standardized_state, standardized_city, standardized_zip, components, maps_url, True

def clean_text(text):
    """Clean text by removing extra spaces, special characters, and HTML tags"""
    if pd.isna(text) or not isinstance(text, str):
        return text
        
    # Decode HTML entities
    text = html.unescape(text)
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Remove special characters except basic punctuation
    text = re.sub(r'[^\w\s,.-]', ' ', text)
    
    # Replace multiple spaces with a single space
    text = re.sub(r'\s+', ' ', text)
    
    # Remove spaces before and after periods, commas
    text = re.sub(r'\s*([.,])\s*', r'\1 ', text)
    
    # Remove leading/trailing spaces
    return text.strip()

def parse_address(address):
    """Parse address into components using usaddress library"""
    try:
        tagged_address, address_type = usaddress.tag(address)
        components = {
            'street_number': '',
            'street_name': '',
            'city': '',
            'state': '',
            'zip_code': ''
        }
        
        # Map usaddress tags to our components
        mapping = {
            'AddressNumber': 'street_number',
            'StreetName': 'street_name',
            'StreetNamePostType': 'street_name',
            'PlaceName': 'city',
            'StateName': 'state',
            'ZipCode': 'zip_code'
        }
        
        for tag, value in tagged_address.items():
            if tag in mapping:
                key = mapping[tag]
                if key == 'street_name' and components[key]:
                    components[key] += ' ' + value
                else:
                    components[key] = value
        
        return components
    except:
        return None

def read_file_content(file, file_extension):
    """Read file content based on file type"""
    if file_extension == 'txt':
        # Read txt file and convert to DataFrame
        content = file.read().decode('utf-8')
        addresses = [line.strip() for line in content.split('\n') if line.strip()]
        return pd.DataFrame({'Address': addresses})
    elif file_extension == 'csv':
        return pd.read_csv(file)
    else:  # xlsx or xls
        return pd.read_excel(file)

def save_file(df, filename, format_type):
    """Save file in specified format with optional Excel formatting"""
    base_filename = os.path.splitext(filename)[0]
    
    if format_type == 'txt':
        output_filename = f"updated_{base_filename}.txt"
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
        
        # Combine all relevant columns into a formatted string
        formatted_addresses = []
        for _, row in df.iterrows():
            if row['Address_Updated']:
                address_parts = []
                if pd.notna(row.get('Standardized_Address')):
                    address_parts.append(row['Standardized_Address'])
                if pd.notna(row.get('Standardized_State')):
                    address_parts.append(row['Standardized_State'])
                if pd.notna(row.get('Maps_URL')):
                    address_parts.append(f"Maps: {row['Maps_URL']}")
                formatted_addresses.append(' | '.join(address_parts))
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(formatted_addresses))
            
    elif format_type == 'csv':
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
        
        # Read the file
        df = read_file_content(file, filename.rsplit('.', 1)[1].lower())
        
        # Find the address, state, city, and ZIP columns
        address_column = find_address_column(df)
        state_column = find_state_column(df)
        city_column = find_city_column(df)
        zip_column = find_zip_column(df)
        
        if not address_column:
            return jsonify({'error': 'No column named "Address" or "Addresses" found in the file'}), 400
        
        # Create new columns for the processed data
        df['Standardized_Address'] = None
        df['Standardized_State'] = None
        df['Standardized_City'] = None
        df['Standardized_ZIP'] = None
        df['Street_Number'] = None
        df['Street_Name'] = None
        df['City'] = None
        df['State'] = None
        df['ZIP_Code'] = None
        df['Maps_URL'] = None
        df['Address_Updated'] = False
        
        # Process each address
        for idx in df.index:
            if pd.notna(df.at[idx, address_column]):
                state_value = df.at[idx, state_column] if state_column else None
                city_value = df.at[idx, city_column] if city_column else None
                zip_value = df.at[idx, zip_column] if zip_column else None
                
                standardized_addr, standardized_state, standardized_city, standardized_zip, components, maps_url, was_updated = process_address(
                    df.at[idx, address_column],
                    state_value,
                    city_value,
                    zip_value
                )
                
                if was_updated:
                    df.at[idx, 'Standardized_Address'] = standardized_addr
                    df.at[idx, 'Standardized_State'] = standardized_state
                    df.at[idx, 'Standardized_City'] = standardized_city
                    df.at[idx, 'Standardized_ZIP'] = standardized_zip
                    if components:
                        df.at[idx, 'Street_Number'] = components['street_number']
                        df.at[idx, 'Street_Name'] = components['street_name']
                        df.at[idx, 'City'] = components['city']
                        df.at[idx, 'State'] = components['state']
                        df.at[idx, 'ZIP_Code'] = components['zip_code']
                    df.at[idx, 'Maps_URL'] = maps_url
                    df.at[idx, 'Address_Updated'] = True
        
        # Save in all formats
        txt_filename, txt_path = save_file(df, filename, 'txt')
        csv_filename, csv_path = save_file(df, filename, 'csv')
        xlsx_filename, xlsx_path = save_file(df, filename, 'xlsx')
        
        return jsonify({
            'success': True,
            'txt_filename': txt_filename,
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