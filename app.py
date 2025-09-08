# Import necessary libraries
from flask import Flask, send_file, abort
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
import requests
import math
import io
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# --- WooCommerce API Constants ---
WOO_URL = os.getenv("WOO_URL")
WOO_API_URL = f"{WOO_URL}/wp-json/wc/v3"
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")

# --- Helper Functions ---

def number_to_words(number):
    """
    Converts a number to Indian currency words.
    """
    def get_unit_word(n):
        units = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine']
        teens = ['ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen',
                 'sixteen', 'seventeen', 'eighteen', 'nineteen']
        tens = ['', '', 'twenty', 'thirty', 'forty', 'fifty',
                'sixty', 'seventy', 'eighty', 'ninety']

        if 0 <= n < 10:
            return units[n]
        elif 10 <= n < 20:
            return teens[n - 10]
        elif 20 <= n < 100:
            return tens[n // 10] + (' ' + units[n % 10] if n % 10 != 0 else '')
        else:
            return ''

    def get_full_word(num):
        num = int(num)
        if num == 0:
            return "zero"
        in_words = []
        lakh = num // 100000
        num %= 100000
        if lakh > 0:
            in_words.append(get_unit_word(lakh) + ' lakh')
        thousand = num // 1000
        num %= 1000
        if thousand > 0:
            in_words.append(get_unit_word(thousand) + ' thousand')
        hundred = num // 100
        num %= 100
        if hundred > 0:
            in_words.append(get_unit_word(hundred) + ' hundred')
        remainder = num
        if remainder > 0:
            if len(in_words) > 0 and (lakh > 0 or thousand > 0 or hundred > 0):
                in_words.append('and')
            in_words.append(get_unit_word(remainder))
        return ' '.join(filter(None, in_words))

    try:
        number = float(number)
    except ValueError:
        return "Invalid amount"
    amount_in_rupees = math.floor(number)
    amount_in_paise = round((number - amount_in_rupees) * 100)
    words = get_full_word(amount_in_rupees)
    if amount_in_paise > 0:
        words += f" and {get_full_word(amount_in_paise)} paise only"
    else:
        words += " only"
    return words.strip().capitalize()

def fetch_order_data_from_api(order_id):
    """
    Fetches order data from the WooCommerce REST API based on the provided JSON structure.
    """
    try:
        endpoint = f"{WOO_API_URL}/orders/{order_id}"
        response = requests.get(endpoint, auth=(CONSUMER_KEY, CONSUMER_SECRET))
        response.raise_for_status()
        
        order = response.json()

        # Calculate subtotal from line_items, as it's not a top-level field.
        items = []
        subtotal = 0
        total_cgst = 0
        total_sgst = 0
        
        # WooCommerce tax is not present in the provided JSON, so we'll re-calculate.
        # This assumes a fixed GST rate. You might need to adjust this.
        cgst_rate = 0.025
        sgst_rate = 0.025
        
        for item in order.get('line_items', []):
            quantity = int(item['quantity'])
            rate = float(item['price'])
            
            # The 'subtotal' in line_items is the net amount (before tax) for that line.
            amount = float(item['subtotal'])
            
            # Recalculate CGST and SGST based on the assumed rates
            cgst_amount = amount * cgst_rate
            sgst_amount = amount * sgst_rate
            total_item_amount = amount + cgst_amount + sgst_amount

            # Assuming HSN/SAC is in the product's meta_data (not in your example)
            hsn_sac = 'N/A' 

            items.append({
                'description': item['name'],
                'hsn_sac': hsn_sac,
                'quantity': quantity,
                'rate': round(rate, 2),
                'cgst_rate': cgst_rate,
                'sgst_rate': sgst_rate,
                'amount': round(amount, 2),
                'cgst_amount': round(cgst_amount, 2),
                'sgst_amount': round(sgst_amount, 2),
                'total': round(total_item_amount, 2)
            })
            
            subtotal += amount
            total_cgst += cgst_amount
            total_sgst += sgst_amount

        total_amount = float(order['total'])
        total_tax = float(order['total_tax'])
        # Calculate rounding based on API totals vs calculated totals
        rounding = total_amount - (subtotal + total_tax)
        
        # Handle the invoice date format
        invoice_date_obj = datetime.strptime(order['date_created'].split('T')[0], '%Y-%m-%d')
        invoice_date_formatted = invoice_date_obj.strftime('%d/%m/%Y')
        
        # Extract billing and shipping data
        billing = order.get('billing', {})
        shipping = order.get('shipping', {})

        return {
            'invoice_number': order.get('number', order_id),
            'invoice_date': invoice_date_formatted,
            'due_date': invoice_date_formatted,
            'place_of_supply': billing.get('state', 'N/A'),
            'client_name': f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip(),
            'client_company': billing.get('company', 'N/A'),
            'client_address': f"{billing.get('address_1', '')}, {billing.get('address_2', '')}, {billing.get('city', '')}, {billing.get('state', '')} {billing.get('postcode', '')}, {billing.get('country', '')}".strip(),
            'client_gstin': 'N/A',
            'ship_to_name': f"{shipping.get('first_name', '')} {shipping.get('last_name', '')}".strip(),
            'ship_to_address': f"{shipping.get('address_1', '')}, {shipping.get('address_2', '')}, {shipping.get('city', '')}, {shipping.get('state', '')} {shipping.get('postcode', '')}, {shipping.get('country', '')}".strip(),
            'ship_to_gstin': 'N/A',
            'items': items,
            'subtotal': round(subtotal, 2),
            'total_cgst': round(total_cgst, 2),
            'total_sgst': round(total_sgst, 2),
            'total_amount': float(order['total']), # Using the total from API for accuracy
            'rounding': round(rounding, 2),
            'total_in_words': number_to_words(total_amount)
        }

    except requests.exceptions.HTTPError as errh:
        if response.status_code == 404:
            return "Order Not Found"
        return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

def generate_invoice_pdf(invoice_data):
    """
    Generates PDF from data using Jinja2 and WeasyPrint.
    Returns PDF content as bytes.
    """
    company_data = {
        'company_name': 'Twig Labs Private Limited',
        'company_address': '6/748, Sector-6, Jankipuram Extension, Lucknow Uttar Pradesh 226031, India',
        'company_gstin': '09AAICT3619H1Z4',
        'bank_name': 'HDFC Bank',
        'account_number': '50100418386629',
        'ifsc_code': 'HDFC0000570',
    }
    final_data = {**company_data, **invoice_data}
    try:
        env = Environment(loader=FileSystemLoader('.'))
        template = env.get_template('invoice_template.html')
    except Exception as e:
        print(f"Error loading template: {e}")
        return None
    html_out = template.render(final_data)
    try:
        pdf_bytes = HTML(string=html_out).write_pdf()
        return pdf_bytes
    except Exception as e:
        print(f"Error generating PDF: {e}")
        return None

# --- Flask Route ---

@app.route('/invoice/<order_id>')
def invoice_route(order_id):
    """
    Main API endpoint to fetch data and generate the invoice PDF.
    """
    invoice_data = fetch_order_data_from_api(order_id)
    if invoice_data is None:
        abort(500, description="Could not fetch order data due to a server or connection error.")
    if invoice_data == "Order Not Found":
        abort(404, description=f"Order ID {order_id} not found in the system.")
    pdf_bytes = generate_invoice_pdf(invoice_data)
    if pdf_bytes is None:
        abort(500, description="Error generating PDF invoice.")
    pdf_buffer = io.BytesIO(pdf_bytes)
    safe_invoice_number = invoice_data["invoice_number"].replace('/', '-')
    file_name = f'invoice_{safe_invoice_number}.pdf'
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=False,
        download_name=file_name
    )

# --- Run Application ---

if __name__ == '__main__':
    app.run(debug=True, port=8010)