import streamlit as st
import json
import os
import io
import base64
import fitz  # pymupdf
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

load_dotenv()

# Support both Streamlit Cloud secrets and local .env
api_key = st.secrets.get("OPENAI_API_KEY", None) or os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

# --- PDF Generation ---

def generate_invoice_pdf(invoice_data: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleBlue", fontSize=16, textColor=colors.HexColor("#1a73e8"), fontName="Helvetica-Bold", spaceAfter=6))
    styles.add(ParagraphStyle(name="SectionHeader", fontSize=10, fontName="Helvetica-Bold", spaceAfter=4, spaceBefore=10))
    styles.add(ParagraphStyle(name="SmallText", fontSize=8, fontName="Helvetica", leading=11))
    styles.add(ParagraphStyle(name="SmallBold", fontSize=8, fontName="Helvetica-Bold", leading=11))
    styles.add(ParagraphStyle(name="RightAligned", fontSize=8, fontName="Helvetica", alignment=TA_RIGHT, leading=11))
    styles.add(ParagraphStyle(name="RightBold", fontSize=8, fontName="Helvetica-Bold", alignment=TA_RIGHT, leading=11))
    styles.add(ParagraphStyle(name="CenterBold", fontSize=9, fontName="Helvetica-Bold", alignment=TA_CENTER))

    elements = []

    # --- Header ---
    supplier = invoice_data.get("supplier", {})
    buyer = invoice_data.get("buyer", {})

    supplier_info = f"""<b>{supplier.get('name', '')}</b><br/>
{supplier.get('address', '')}<br/>
GSTIN: {supplier.get('gstin', '')}<br/>
Phone: {supplier.get('phone', '')}"""

    buyer_info = f"""<b>Bill To:</b><br/>
<b>{buyer.get('name', '')}</b><br/>
{buyer.get('address', '')}<br/>
GSTIN: {buyer.get('gstin', '')}<br/>
Phone: {buyer.get('phone', '')}"""

    header_table = Table(
        [[Paragraph(supplier_info, styles["SmallText"]),
          Paragraph(buyer_info, styles["SmallText"])]],
        colWidths=[doc.width / 2] * 2
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 6 * mm))

    # --- Invoice Title ---
    inv_number = invoice_data.get("invoice_number", "INV-001")
    elements.append(Paragraph(f"Invoice #{inv_number}", styles["TitleBlue"]))

    # --- Meta info ---
    meta_data = [
        ["Invoice Date:", invoice_data.get("invoice_date", ""),
         "PO Reference:", invoice_data.get("po_reference", "")],
        ["Due Date:", invoice_data.get("due_date", ""),
         "Payment Terms:", invoice_data.get("payment_terms", "")],
    ]
    meta_table = Table(meta_data, colWidths=[80, 110, 80, 110])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 6 * mm))

    # --- Shipping address ---
    shipping = invoice_data.get("shipping_address", "")
    if shipping:
        elements.append(Paragraph("Ship To:", styles["SectionHeader"]))
        elements.append(Paragraph(shipping.replace("\n", "<br/>"), styles["SmallText"]))
        elements.append(Spacer(1, 4 * mm))

    # --- Line items table ---
    line_items = invoice_data.get("line_items", [])
    table_header = ["#", "Description", "Qty", "Unit Price", "Disc.%", "Tax%", "Amount"]
    table_data = [table_header]

    for i, item in enumerate(line_items, 1):
        qty = float(item.get("qty", 0))
        unit_price = float(item.get("unit_price", 0))
        discount = float(item.get("discount_pct", 0))
        tax_pct = float(item.get("tax_pct", 0))
        base = qty * unit_price
        after_disc = base * (1 - discount / 100)
        amount = after_disc
        table_data.append([
            str(i),
            Paragraph(item.get("description", ""), styles["SmallText"]),
            f"{qty:g}",
            f"{unit_price:,.2f}",
            f"{discount:.1f}%",
            f"GST {tax_pct:.0f}%",
            f"Rs. {amount:,.2f}",
        ])

    col_widths = [20, 180, 45, 65, 40, 50, 70]
    item_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a73e8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4ff")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(item_table)
    elements.append(Spacer(1, 4 * mm))

    # --- Totals ---
    untaxed = float(invoice_data.get("untaxed_amount", 0))
    tax_amount = float(invoice_data.get("tax_amount", 0))
    total = float(invoice_data.get("total_amount", 0))

    totals_data = [
        ["", "Untaxed Amount:", f"Rs. {untaxed:,.2f}"],
        ["", "GST:", f"Rs. {tax_amount:,.2f}"],
        ["", "Total:", f"Rs. {total:,.2f}"],
    ]
    totals_table = Table(totals_data, colWidths=[300, 100, 70])
    totals_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (1, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEABOVE", (1, -1), (-1, -1), 1, colors.HexColor("#1a73e8")),
        ("TEXTCOLOR", (1, -1), (-1, -1), colors.HexColor("#1a73e8")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 8 * mm))

    # --- Bank details / notes ---
    notes = invoice_data.get("notes", "")
    if notes:
        elements.append(Paragraph("Notes / Bank Details:", styles["SectionHeader"]))
        elements.append(Paragraph(notes.replace("\n", "<br/>"), styles["SmallText"]))

    # --- Build ---
    doc.build(elements)
    buffer.seek(0)
    return buffer.read()


# --- OpenAI invoice structuring ---

def structure_invoice_with_ai(po_data: dict) -> dict:
    prompt = f"""You are an invoice generation assistant. Given the following Purchase Order data, generate a structured JSON for an invoice.

Purchase Order Data:
{json.dumps(po_data, indent=2)}

Generate a valid JSON object with these exact keys:
{{
  "invoice_number": "INV-<generate a sequential number>",
  "invoice_date": "<today's date in DD/MM/YYYY>",
  "due_date": "<based on payment terms>",
  "po_reference": "<PO number from input>",
  "payment_terms": "<from input>",
  "supplier": {{
    "name": "<supplier company name>",
    "address": "<full supplier address>",
    "gstin": "<supplier GSTIN>",
    "phone": "<supplier phone>"
  }},
  "buyer": {{
    "name": "<buyer company name>",
    "address": "<full buyer address>",
    "gstin": "<buyer GSTIN if available>",
    "phone": "<buyer phone>"
  }},
  "shipping_address": "<shipping address as a single string>",
  "line_items": [
    {{
      "description": "<item description>",
      "qty": <quantity>,
      "unit_price": <unit price>,
      "discount_pct": <discount percentage>,
      "tax_pct": <tax percentage number only, e.g. 18>
    }}
  ],
  "untaxed_amount": <sum of line amounts before tax>,
  "tax_amount": <total tax>,
  "total_amount": <grand total>,
  "notes": "Thank you for your business."
}}

IMPORTANT: Return ONLY the JSON object, no markdown, no extra text. Calculate all amounts correctly."""

    response = client.chat.completions.create(
        model="gpt-5.4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )

    content = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0]
    return json.loads(content)


# --- Extract PO from uploaded file ---

def file_to_base64_images(uploaded_file) -> list[str]:
    """Convert uploaded PDF or image to list of base64-encoded PNG images."""
    images = []
    file_bytes = uploaded_file.read()
    file_type = uploaded_file.type

    if file_type == "application/pdf":
        pdf = fitz.open(stream=file_bytes, filetype="pdf")
        for page in pdf:
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            images.append(base64.b64encode(img_bytes).decode("utf-8"))
        pdf.close()
    else:
        images.append(base64.b64encode(file_bytes).decode("utf-8"))

    return images


def extract_and_generate_invoice_from_file(uploaded_file) -> dict:
    """Use GPT-5.4 vision to extract PO data and generate invoice JSON in a single call."""
    images_b64 = file_to_base64_images(uploaded_file)

    today = datetime.today()
    today_str = today.strftime("%d/%m/%Y")

    content_parts = [
        {"type": "text", "text": f"""Extract ALL Purchase Order information from this document and generate a complete invoice JSON.
Today's date is {today_str}.

Return a JSON object with these exact keys:
{{
  "po_data": {{
    "po_number": "",
    "order_date": "DD/MM/YYYY",
    "expected_arrival": "DD/MM/YYYY",
    "payment_terms": "",
    "buyer_department": "",
    "buyer": {{"name": "", "address": "", "gstin": "", "phone": ""}},
    "supplier": {{"name": "", "address": "", "gstin": "", "phone": ""}},
    "shipping_address": "",
    "line_items": [{{"description": "", "qty": 0, "unit_price": 0, "discount_pct": 0, "tax_pct": 18}}]
  }},
  "invoice": {{
    "invoice_number": "INV-<generate a sequential number>",
    "invoice_date": "{today_str}",
    "due_date": "<based on payment terms from PO>",
    "po_reference": "<PO number from document>",
    "payment_terms": "<from document>",
    "supplier": {{"name": "", "address": "", "gstin": "", "phone": ""}},
    "buyer": {{"name": "", "address": "", "gstin": "", "phone": ""}},
    "shipping_address": "<shipping address as a single string>",
    "line_items": [
      {{"description": "", "qty": 0, "unit_price": 0, "discount_pct": 0, "tax_pct": 18}}
    ],
    "untaxed_amount": 0,
    "tax_amount": 0,
    "total_amount": 0,
    "notes": "Thank you for your business."
  }}
}}

IMPORTANT:
- Return ONLY the JSON object, no markdown, no extra text.
- Calculate all amounts correctly: untaxed = sum of (qty * unit_price * (1 - discount/100)), tax = sum of (line_untaxed * tax_pct/100), total = untaxed + tax.
- Use empty strings for missing fields."""}
    ]

    for img_b64 in images_b64:
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"}
        })

    response = client.chat.completions.create(
        model="gpt-5.4",
        messages=[{"role": "user", "content": content_parts}],
        temperature=0.1,
    )

    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0]
    return json.loads(content)


# --- Streamlit UI ---

st.set_page_config(page_title="PO to Invoice Generator", layout="wide")
st.title("Purchase Order to Invoice Generator")
st.markdown("Upload a PO file to auto-fill, or enter details manually below.")

# Initialize session state for extracted PO data
if "po_extracted" not in st.session_state:
    st.session_state.po_extracted = None

# --- File Upload Section ---
st.subheader("Upload Purchase Order (Optional)")
uploaded_po = st.file_uploader(
    "Upload PO as PDF or Image",
    type=["pdf", "png", "jpg", "jpeg", "webp"],
    help="Upload a Purchase Order PDF or image to auto-extract all details using AI.",
)

if uploaded_po and st.button("Extract & Generate Invoice", type="primary"):
    with st.spinner("Step 1/2: Extracting PO & generating invoice with GPT-5.4 Vision..."):
        try:
            result = extract_and_generate_invoice_from_file(uploaded_po)
            extracted = result.get("po_data", {})
            invoice_data = result.get("invoice", {})

            st.session_state.po_extracted = extracted
            st.session_state.invoice_data = invoice_data

            # Update line item widget keys so form fields pick up extracted values
            ext_line_items = extracted.get("line_items", [])
            st.session_state["num_line_items"] = max(len(ext_line_items), 1)
            for idx, item in enumerate(ext_line_items):
                st.session_state[f"desc_{idx}"] = item.get("description", "")
                st.session_state[f"qty_{idx}"] = float(item.get("qty", 1.0))
                st.session_state[f"price_{idx}"] = float(item.get("unit_price", 0.0))
                st.session_state[f"disc_{idx}"] = float(item.get("discount_pct", 0.0))
                tax_val = int(item.get("tax_pct", 18))
                if tax_val in [0, 5, 12, 18, 28]:
                    st.session_state[f"tax_{idx}"] = tax_val

            # Update buyer/supplier widget keys too
            ext_b = extracted.get("buyer", {})
            ext_s = extracted.get("supplier", {})
            if ext_b.get("name"):
                st.session_state["buyer_co"] = ext_b.get("name", "")
                st.session_state["buyer_addr"] = ext_b.get("address", "")
                st.session_state["buyer_gstin"] = ext_b.get("gstin", "")
                st.session_state["buyer_phone"] = ext_b.get("phone", "")
            if ext_s.get("name"):
                st.session_state["supp_co"] = ext_s.get("name", "")
                st.session_state["supp_addr"] = ext_s.get("address", "")
                st.session_state["supp_gstin"] = ext_s.get("gstin", "")
                st.session_state["supp_phone"] = ext_s.get("phone", "")

            st.success("PO extracted & invoice generated in a single AI call!")
        except Exception as e:
            st.error(f"Failed to extract and generate invoice: {e}")
            st.stop()

    with st.spinner("Step 2/2: Generating PDF..."):
        pdf_bytes = generate_invoice_pdf(invoice_data)
        st.session_state.invoice_pdf = pdf_bytes
        st.session_state.invoice_filename = f"Invoice_{invoice_data.get('invoice_number', 'INV')}.pdf"

    st.balloons()

# Show download button if invoice PDF is ready from upload flow
if st.session_state.get("invoice_pdf"):
    st.markdown("---")
    st.subheader("Invoice Ready!")

    dl_col1, dl_col2 = st.columns([1, 1])
    with dl_col1:
        st.download_button(
            label="Download Invoice PDF",
            data=st.session_state.invoice_pdf,
            file_name=st.session_state.get("invoice_filename", "Invoice.pdf"),
            mime="application/pdf",
            type="primary",
            use_container_width=True,
            key="dl_upload_flow",
        )
    with dl_col2:
        with st.expander("View Extracted Invoice Data"):
            st.json(st.session_state.get("invoice_data", {}))

ext = st.session_state.po_extracted or {}
ext_buyer = ext.get("buyer", {})
ext_supplier = ext.get("supplier", {})
ext_items = ext.get("line_items", [])

st.divider()
st.markdown("**Or fill in details manually below:**")

# --- Line item count (outside form so changes apply immediately) ---
default_num_items = max(len(ext_items), 1)
if "num_line_items" not in st.session_state:
    st.session_state.num_line_items = default_num_items

num_items = st.number_input(
    "Number of line items", min_value=1, max_value=20,
    value=st.session_state.num_line_items, key="num_line_items",
)

# Clean up session state keys for removed line items
for i in range(int(num_items), 20):
    for prefix in ("desc_", "qty_", "price_", "disc_", "tax_"):
        st.session_state.pop(f"{prefix}{i}", None)

# --- Manual Form (pre-filled if extracted) ---
with st.form("po_form"):
    st.subheader("Purchase Order Info")
    col1, col2 = st.columns(2)
    with col1:
        po_number = st.text_input("PO Number", value=ext.get("po_number", ""), placeholder="e.g. MCGPL/PO/25-26/00414")
        order_date = st.date_input("Order Date", value=datetime.today())
        payment_terms = st.text_input("Payment Terms", value=ext.get("payment_terms", "45 Days"))
    with col2:
        expected_arrival = st.date_input("Expected Arrival", value=datetime.today() + timedelta(days=30))
        buyer_name_input = st.text_input("Buyer Department", value=ext.get("buyer_department", "Purchase"))

    st.divider()

    # Buyer (company placing the PO)
    st.subheader("Buyer Details (Your Company)")
    bc1, bc2 = st.columns(2)
    with bc1:
        buyer_company = st.text_input("Company Name", value=ext_buyer.get("name", "MELUX CONTROL GEARS PRIVATE LIMITED"), key="buyer_co")
        buyer_address = st.text_area("Address", value=ext_buyer.get("address", "408/410 MATE CHEMBARS GULTAKADI\nMUKUNDNAGAR\nPune 411037\nMaharashtra MH, India"), key="buyer_addr")
    with bc2:
        buyer_gstin = st.text_input("GSTIN", value=ext_buyer.get("gstin", ""), key="buyer_gstin", placeholder="e.g. 27AAACM1234A1Z5")
        buyer_phone = st.text_input("Phone", value=ext_buyer.get("phone", "+912024264895"), key="buyer_phone")

    st.divider()

    # Supplier
    st.subheader("Supplier Details")
    sc1, sc2 = st.columns(2)
    with sc1:
        supplier_name = st.text_input("Company Name", value=ext_supplier.get("name", "Siddhant Neuracer"), key="supp_co")
        supplier_address = st.text_area("Address", value=ext_supplier.get("address", "MCECHS Layout\nBangalore 560077\nKarnataka, India"), key="supp_addr")
    with sc2:
        supplier_gstin = st.text_input("GSTIN", value=ext_supplier.get("gstin", "12345CJIPJ24"), key="supp_gstin")
        supplier_phone = st.text_input("Phone", value=ext_supplier.get("phone", "+917014943090"), key="supp_phone")

    st.divider()

    # Shipping address
    st.subheader("Shipping Address")
    shipping_address = st.text_area(
        "Shipping Address",
        value=ext.get("shipping_address", "MELUX CONTROL GEARS PRIVATE LIMITED\n408/MATE CHEMBARS\nMUKUNDNAGAR, GULTEKDI\nPUNE 411037\nMaharashtra MH, India"),
    )

    st.divider()

    # Line items
    st.subheader("Line Items")

    TAX_OPTIONS = [0, 5, 12, 18, 28]

    items = []
    for i in range(int(st.session_state.get("num_line_items", max(len(ext_items), 1)))):
        st.markdown(f"**Item {i + 1}**")
        ei = ext_items[i] if i < len(ext_items) else {}
        ic1, ic2, ic3, ic4, ic5 = st.columns([3, 1, 1, 1, 1])
        with ic1:
            desc = st.text_area("Description", key=f"desc_{i}", height=80, value=ei.get("description", ""), placeholder="Item description...")
        with ic2:
            qty = st.number_input("Qty", key=f"qty_{i}", min_value=0.0, value=float(ei.get("qty", 1.0)), step=0.5)
        with ic3:
            unit_price = st.number_input("Unit Price (Rs.)", key=f"price_{i}", min_value=0.0, value=float(ei.get("unit_price", 0.0)), step=0.01)
        with ic4:
            discount = st.number_input("Discount %", key=f"disc_{i}", min_value=0.0, max_value=100.0, value=float(ei.get("discount_pct", 0.0)))
        with ic5:
            tax_val = int(ei.get("tax_pct", 18))
            tax_idx = TAX_OPTIONS.index(tax_val) if tax_val in TAX_OPTIONS else 3
            tax = st.selectbox("Tax %", key=f"tax_{i}", options=TAX_OPTIONS, index=tax_idx)
        items.append({
            "description": desc,
            "qty": qty,
            "unit_price": unit_price,
            "discount_pct": discount,
            "tax_pct": tax,
        })

    submitted = st.form_submit_button("Generate Invoice", type="primary", use_container_width=True)

if submitted:
    if not po_number:
        st.error("Please enter a PO Number.")
    elif not supplier_name:
        st.error("Please enter Supplier details.")
    elif all(item["qty"] == 0 or item["unit_price"] == 0 for item in items):
        st.error("Please add at least one line item with quantity and price.")
    else:
        po_data = {
            "po_number": po_number,
            "order_date": order_date.strftime("%d/%m/%Y"),
            "expected_arrival": expected_arrival.strftime("%d/%m/%Y"),
            "payment_terms": payment_terms,
            "buyer_department": buyer_name_input,
            "buyer": {
                "name": buyer_company,
                "address": buyer_address,
                "gstin": buyer_gstin,
                "phone": buyer_phone,
            },
            "supplier": {
                "name": supplier_name,
                "address": supplier_address,
                "gstin": supplier_gstin,
                "phone": supplier_phone,
            },
            "shipping_address": shipping_address,
            "line_items": items,
        }

        with st.spinner("Generating invoice with AI (GPT-5.4)..."):
            try:
                invoice_data = structure_invoice_with_ai(po_data)

                # Override supplier/buyer with original form values so PDF is accurate
                invoice_data["supplier"] = po_data["supplier"]
                invoice_data["buyer"] = po_data["buyer"]
                invoice_data["shipping_address"] = po_data["shipping_address"]

                st.success("Invoice structured successfully!")

                # Show preview
                with st.expander("View Invoice JSON", expanded=False):
                    st.json(invoice_data)

                # Generate PDF
                pdf_bytes = generate_invoice_pdf(invoice_data)

                st.download_button(
                    label="Download Invoice PDF",
                    data=pdf_bytes,
                    file_name=f"Invoice_{invoice_data.get('invoice_number', 'INV')}.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                    key="dl_manual_flow",
                )

                st.balloons()

            except json.JSONDecodeError as e:
                st.error(f"Failed to parse AI response as JSON: {e}")
            except Exception as e:
                st.error(f"Error: {e}")
