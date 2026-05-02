"""
IOCL Bill Generator – Streamlit web UI
Run with:  streamlit run app.py
"""

import io
import os
import tempfile
import zipfile
from datetime import date

import streamlit as st

from generator import generate_bills_pdf, split_amount

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="IndianOil Bill Generator",
    page_icon="🛢️",
    layout="centered",
)

st.title("🛢️ IndianOil Bill Generator")
st.markdown(
    "Generate scanned-style **IndianOil** petrol pump receipts in PDF format."
)

# ── Input form ────────────────────────────────────────────────────────────────
with st.form("bill_form"):

    st.subheader("Pump & Vehicle Details")
    col_a, col_b = st.columns(2)

    with col_a:
        address = st.text_area(
            "Pump Address (one line per \\n)",
            value="Ring Rd, Nehru Nagar,\nLajpat Nagar, New Delhi,\nDelhi 110065",
            height=110,
            help="Exactly as it should appear on the bill – use newlines to break lines.",
        )
        vehicle_no = st.text_input(
            "Vehicle Number",
            value="HP07E0813",
            help="E.g. DL01AB1234",
        )

    with col_b:
        fuel = st.selectbox("Fuel Type", ["Diesel", "Petrol", "CNG", "XP95", "XP100"])
        rate = st.number_input(
            "Rate (Rs./Ltr)",
            min_value=50.0,
            max_value=250.0,
            value=87.67,
            step=0.01,
            format="%.2f",
        )

    st.divider()
    st.subheader("Date Range & Amount")
    col_c, col_d = st.columns(2)

    with col_c:
        start_date = st.date_input("Start Date", value=date(2026, 4, 1))
        total_amount = st.number_input(
            "Total Amount to Split (Rs.)",
            min_value=500.0,
            max_value=10_000_000.0,
            value=35000.0,
            step=500.0,
            format="%.2f",
            help="Sum of all generated bills will equal this value.",
        )

    with col_d:
        end_date = st.date_input("End Date", value=date(2026, 4, 30))
        max_volume = st.number_input(
            "Max Volume per Bill (Ltr)",
            min_value=5.0,
            max_value=500.0,
            value=60.0,
            step=1.0,
            format="%.2f",
            help=(
                "Upper limit of litres for a single transaction. "
                "Each bill's Volume is back-calculated as Sale ÷ Rate."
            ),
        )

    num_bills = st.slider(
        "Number of Bills",
        min_value=2,
        max_value=10,
        value=7,
        help="How many individual bills to generate (2–10).",
    )

    submitted = st.form_submit_button("⚙️ Generate Bills", type="primary", use_container_width=True)

# ── Validation & generation ───────────────────────────────────────────────────
if submitted:
    # Basic input validation
    errs = []

    if start_date >= end_date:
        errs.append("End date must be **after** start date.")

    max_sale_per_bill = round(max_volume * rate, 2)
    max_possible      = round(max_sale_per_bill * num_bills, 2)

    if total_amount > max_possible:
        errs.append(
            f"Total Rs. {total_amount:,.2f} exceeds the maximum possible total "
            f"({num_bills} bills × Rs. {max_sale_per_bill:,.2f} = "
            f"Rs. {max_possible:,.2f}). "
            "Increase **Max Volume per Bill** or reduce **Total Amount**."
        )

    if errs:
        for e in errs:
            st.error(e)
        st.stop()

    # ── Generate ──────────────────────────────────────────────────────────────
    progress = st.progress(0, text="Generating bills…")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        output_path = tmp.name

    try:
        bills = generate_bills_pdf(
            address      = address,
            vehicle_no   = vehicle_no,
            start_date   = start_date,
            end_date     = end_date,
            fuel         = fuel,
            rate         = rate,
            total_amount = total_amount,
            max_volume   = max_volume,
            output_path  = output_path,
            num_bills    = num_bills,
        )
        progress.progress(100, text="Done!")
    except Exception as exc:
        st.error(f"Generation failed: {exc}")
        st.stop()

    # ── Results ───────────────────────────────────────────────────────────────
    n_bills    = len(bills)
    actual_sum = sum(b["sale"] for b in bills)

    st.success(f"✅ Generated **{n_bills} bills** — total Rs. {actual_sum:,.2f}")

    # Summary table (no pandas needed)
    st.subheader("Bill Summary")
    table_rows = [
        {
            "Bill No":       b["bill_no"],
            "Date":          b["date"],
            "Time":          b["time"],
            "Sale Amount":   f"Rs. {b['sale']:,.2f}",
            "Volume":        f"{b['volume']:.2f} Ltr",
        }
        for b in bills
    ]
    st.table(table_rows)

    # Verification note
    diff = round(actual_sum - total_amount, 2)
    if diff == 0:
        st.info(f"✔ Sum of bills = Rs. {actual_sum:,.2f} (matches entered total exactly)")
    else:
        st.info(
            f"✔ Sum of bills = Rs. {actual_sum:,.2f}  "
            f"| Entered total = Rs. {total_amount:,.2f}  "
            f"| Difference = Rs. {diff:+.2f}  *(rounding)*"
        )

    # ── Preview first bill ────────────────────────────────────────────────────
    st.subheader("Preview (first bill)")
    try:
        import fitz  # PyMuPDF

        doc  = fitz.open(output_path)
        page = doc[0]
        mat  = fitz.Matrix(1.5, 1.5)
        pix  = page.get_pixmap(matrix=mat)

        st.image(pix.tobytes("png"), use_container_width=True)
        doc.close()
    except Exception:
        st.info("Install PyMuPDF (`pip install pymupdf`) to see a bill preview here.")

    # ── Build ZIP of individual single-page PDFs ──────────────────────────────
    try:
        import fitz
        src_doc = fitz.open(output_path)
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, bill in enumerate(bills):
                single = fitz.open()          # blank PDF
                single.insert_pdf(src_doc, from_page=i, to_page=i)
                pdf_bytes = single.tobytes()
                single.close()
                fname = f"bill_{bill['bill_no']}_{bill['date'].replace('/', '')}.pdf"
                zf.writestr(fname, pdf_bytes)
        src_doc.close()
        zip_buf.seek(0)

        st.download_button(
            label     = f"📥 Download All {n_bills} Bills (ZIP)",
            data      = zip_buf,
            file_name = "iocl_bills.zip",
            mime      = "application/zip",
            use_container_width=True,
        )
    except Exception as exc:
        st.warning(f"Could not build ZIP: {exc}")
        with open(output_path, "rb") as fh:
            st.download_button(
                label     = "📥 Download Bills PDF",
                data      = fh.read(),
                file_name = "iocl_bills.pdf",
                mime      = "application/pdf",
                use_container_width=True,
            )

    os.unlink(output_path)
