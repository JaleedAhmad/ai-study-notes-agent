from fpdf import FPDF
import markdown

def generate_pdf(md_text):
    html = markdown.markdown(md_text)
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    
    # fpdf2 write_html supports basic html styling like bold, headers, list items
    # We replace characters that helvetica doesn't support by latin-1 encoding
    safe_html = html.encode('latin-1', 'replace').decode('latin-1')
    try:
        pdf.write_html(safe_html)
    except Exception as e:
        # Fallback to plain text if HTML parsing fails
        pdf.multi_cell(0, 10, txt=md_text.encode('latin-1', 'replace').decode('latin-1'))
        
    return bytes(pdf.output())
