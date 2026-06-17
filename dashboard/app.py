"""
AI Invoice & Document Processing Automation System - Dashboard.

Run with:
    streamlit run dashboard/app.py

Configure the backend URL with the API_BASE_URL environment variable
(defaults to http://localhost:8000).

Pages (matching the project spec):
  Home              - system summary metrics
  Upload Document   - upload PDF/image, select expected type, add notes
  Document List     - table of all documents
  Document Detail    - file preview, extracted text, classification, fields
  Review & Edit     - editable fields, approve/reject/request correction
  Validation Results - error/warning/info issue list
  Export            - export approved documents to CSV/JSON
  Audit Logs        - full event history
  Demo Mode         - load sample documents
"""

import json
from datetime import datetime

import streamlit as st

from api_client import API_BASE_URL, file_url, get, patch, post

st.set_page_config(page_title="AI Document Processing Automation", layout="wide")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATUS_BADGES = {
    "uploaded": "📤 uploaded",
    "text_extracted": "📄 text extracted",
    "extraction_failed": "❌ extraction failed",
    "classified": "🏷️ classified",
    "extracted": "🔎 extracted",
    "validated": "✅ validated",
    "pending_review": "🟡 pending review",
    "needs_correction": "✏️ needs correction",
    "approved": "🟢 approved",
    "rejected": "🔴 rejected",
    "exported": "📦 exported",
}

VALIDATION_BADGES = {
    "valid": "✅ valid",
    "warning": "🟠 warning",
    "failed": "🔴 failed",
    "requires_review": "🟡 requires review",
}

DOC_TYPE_LABELS = {
    "invoice": "🧾 Invoice",
    "receipt": "🧍 Receipt",
    "purchase_order": "📦 Purchase Order",
    "contract": "📜 Contract",
    "unknown": "❓ Unknown",
}

ISSUE_ICONS = {"error": "🔴", "warning": "🟠", "info": "ℹ️"}


def fmt_dt(value):
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def show_error(error):
    if error:
        st.error(error)
        return True
    return False


def doc_label(doc):
    type_label = DOC_TYPE_LABELS.get(doc.get("document_type") or "", doc.get("document_type") or "unclassified")
    return f"#{doc['id']} - {doc['filename']} ({type_label})"


def download_link_markdown(label, log_id, export_type):
    url = file_url(f"/export/download/{log_id}")
    return f"[{label}]({url})"


# ---------------------------------------------------------------------------
# Page: Home
# ---------------------------------------------------------------------------

def page_home():
    st.title("📑 AI Invoice & Document Processing Automation System")
    st.caption("AI recommends. Validation checks. Human approves. System exports.")

    health, error = get("/health")
    if show_error(error):
        st.info(f"Make sure the backend is running and reachable at **{API_BASE_URL}**.")
        return

    cols = st.columns(4)
    cols[0].metric("Status", health["status"].upper())
    cols[1].metric("Environment", health["env"])
    cols[2].metric("Demo mode", "ON" if health["demo_mode"] else "OFF")
    cols[3].metric("Database", "connected" if health["database_connected"] else "unreachable")

    if health["demo_mode"]:
        st.success(
            "Demo mode is ON - text extraction and AI classification/extraction use "
            "built-in sample data, so you can test the full pipeline without Tesseract "
            "or an AI API key."
        )

    st.divider()
    st.subheader("Document pipeline snapshot")

    metrics, error = get("/dashboard/metrics")
    if show_error(error):
        return

    cols = st.columns(6)
    cols[0].metric("Total documents", metrics["total_documents"])
    cols[1].metric("Processed", metrics["processed_documents"])
    cols[2].metric("Pending review", metrics["pending_review"])
    cols[3].metric("Approved", metrics["approved_documents"])
    cols[4].metric("Rejected", metrics["rejected_documents"])
    cols[5].metric("Exported", metrics["exported_documents"])

    if metrics.get("average_confidence") is not None:
        st.caption(f"Average AI extraction confidence: **{metrics['average_confidence']:.2f}**")

    st.divider()
    st.subheader("Get started")
    st.markdown(
        "1. Go to **Demo Mode** and click **Load Sample Documents** (or go to "
        "**Upload Document** to upload your own PDF/image).\n"
        "2. Open **Document List**, pick a document, and step through "
        "**Document Detail**: extract text -> classify -> extract fields -> validate.\n"
        "3. Go to **Review & Edit** to correct any flagged fields and approve or reject.\n"
        "4. Use **Export** to download approved documents as CSV or JSON.\n"
        "5. Check **Audit Logs** to see the full trace of everything that happened."
    )


# ---------------------------------------------------------------------------
# Page: Upload Document
# ---------------------------------------------------------------------------

def page_upload():
    st.title("📤 Upload Document")
    st.caption("Accepted file types: PDF, PNG, JPG, JPEG.")

    uploaded_file = st.file_uploader("Choose a file", type=["pdf", "png", "jpg", "jpeg"])
    expected_type = st.selectbox(
        "Expected document type (optional)",
        options=["(none)", "invoice", "receipt", "purchase_order", "contract"],
    )
    notes = st.text_area("Notes (optional)")

    if st.button("Upload and start processing", type="primary", disabled=uploaded_file is None):
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
        data = {}
        if expected_type != "(none)":
            data["expected_document_type"] = expected_type
        if notes:
            data["notes"] = notes

        result, error = post("/documents/upload", files=files, data=data)
        if not show_error(error):
            st.success(result["message"])
            st.info(f"Document #{result['document']['id']} created. Go to **Document Detail** to process it.")


# ---------------------------------------------------------------------------
# Page: Document List
# ---------------------------------------------------------------------------

def page_document_list():
    st.title("📋 Document List")

    status_filter = st.selectbox(
        "Filter by status",
        options=["(all)"] + list(STATUS_BADGES.keys()),
    )

    params = {"limit": 200}
    if status_filter != "(all)":
        params["status"] = status_filter

    documents, error = get("/documents", params=params)
    if show_error(error):
        return

    if not documents:
        st.info("No documents yet. Go to **Upload Document** or **Demo Mode** to add some.")
        return

    rows = []
    for doc in documents:
        rows.append(
            {
                "ID": doc["id"],
                "Filename": doc["filename"],
                "Type": DOC_TYPE_LABELS.get(doc.get("document_type") or "", "-"),
                "Status": STATUS_BADGES.get(doc["status"], doc["status"]),
                "Confidence": (
                    f"{doc['classification_confidence']:.2f}" if doc.get("classification_confidence") is not None else "-"
                ),
                "Uploaded": fmt_dt(doc["upload_time"]),
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(f"{len(documents)} document(s). Open **Document Detail** and select a document by ID to process it.")


# ---------------------------------------------------------------------------
# Page: Document Detail
# ---------------------------------------------------------------------------

def page_document_detail():
    st.title("🔍 Document Detail")

    documents, error = get("/documents", params={"limit": 200})
    if show_error(error):
        return
    if not documents:
        st.info("No documents yet. Go to **Upload Document** or **Demo Mode** to add some.")
        return

    options = {doc_label(d): d["id"] for d in documents}
    selected_label = st.selectbox("Select a document", list(options.keys()))
    document_id = options[selected_label]

    doc, error = get(f"/documents/{document_id}")
    if show_error(error):
        return

    st.markdown(f"### {doc['filename']}")
    st.caption(f"Status: {STATUS_BADGES.get(doc['status'], doc['status'])}  |  Uploaded: {fmt_dt(doc['upload_time'])}")

    if doc.get("notes"):
        st.caption(f"Notes: {doc['notes']}")

    col_preview, col_pipeline = st.columns([1, 1])

    with col_preview:
        st.subheader("Original file")
        if doc["file_type"] in ("png", "jpg", "jpeg"):
            st.image(file_url(f"/documents/{document_id}/file"))
        else:
            pdf_url = file_url(f"/documents/{document_id}/file")
            st.markdown(f"[Open PDF]({pdf_url})")

    with col_pipeline:
        st.subheader("Pipeline")

        if st.button("1️⃣ Extract text"):
            result, error = post(f"/documents/{document_id}/extract")
            if not show_error(error):
                st.rerun()

        text_record = doc.get("extracted_text")
        if text_record:
            status_icon = "✅" if text_record["extraction_status"] == "success" else "❌"
            st.caption(
                f"{status_icon} Method: {text_record['extraction_method']} | "
                f"Confidence: {text_record.get('extraction_confidence')}"
            )
            if text_record["extraction_status"] == "failed":
                st.error(text_record.get("error_message"))
            with st.expander("Extracted text"):
                st.text(text_record["raw_text"])

        if text_record and text_record["extraction_status"] == "success":
            if st.button("2️⃣ Classify document type"):
                result, error = post(f"/documents/{document_id}/classify")
                if not show_error(error):
                    st.rerun()

        if doc.get("document_type"):
            st.caption(
                f"Classified as: {DOC_TYPE_LABELS.get(doc['document_type'], doc['document_type'])} "
                f"(confidence={doc.get('classification_confidence')})"
            )
            if doc.get("classification_reason"):
                st.caption(f"Reason: {doc['classification_reason']}")

        if doc.get("document_type") and doc["document_type"] != "unknown":
            force = doc["status"] == "pending_review"
            extract_label = "3️⃣ Extract fields" + (" (force)" if force else "")
            if st.button(extract_label):
                params = {"force": "true"} if force else None
                result, error = post(f"/documents/{document_id}/extract-fields", params=params)
                if not show_error(error):
                    st.rerun()

        extracted_data = doc.get("extracted_data")
        if extracted_data:
            st.caption(f"Summary: {extracted_data['summary']}")
            with st.expander("Extracted fields (raw)"):
                st.json(extracted_data["extracted_fields"])
            if extracted_data.get("missing_fields"):
                st.warning(f"Missing fields: {', '.join(extracted_data['missing_fields'])}")
            if extracted_data.get("uncertain_fields"):
                st.info(f"Uncertain fields: {', '.join(extracted_data['uncertain_fields'])}")

        if extracted_data:
            if st.button("4️⃣ Validate"):
                result, error = post(f"/documents/{document_id}/validate")
                if not show_error(error):
                    st.rerun()

        validation = doc.get("validation_result")
        if validation:
            st.markdown(f"**Validation: {VALIDATION_BADGES.get(validation['status'], validation['status'])}**")
            for issue in validation.get("issues") or []:
                icon = ISSUE_ICONS.get(issue["level"], "•")
                st.markdown(f"{icon} `{issue['rule']}` - {issue['message']}")

            st.info("Go to **Review & Edit** to correct fields, then approve or reject this document.")


# ---------------------------------------------------------------------------
# Page: Review & Edit
# ---------------------------------------------------------------------------

def page_review_edit():
    st.title("✏️ Review & Edit")

    documents, error = get("/documents", params={"status": "pending_review", "limit": 200})
    if show_error(error):
        return
    correction_docs, error = get("/documents", params={"status": "needs_correction", "limit": 200})
    if not show_error(error):
        documents = documents + correction_docs

    if not documents:
        st.info("No documents waiting for review. Process a document in **Document Detail** first.")
        return

    options = {doc_label(d): d["id"] for d in documents}
    selected_label = st.selectbox("Select a document to review", list(options.keys()))
    document_id = options[selected_label]

    doc, error = get(f"/documents/{document_id}")
    if show_error(error):
        return

    extracted_data = doc.get("extracted_data")
    if not extracted_data:
        st.warning("This document has no extracted fields yet.")
        return

    validation = doc.get("validation_result")
    if validation:
        st.markdown(f"**Validation status: {VALIDATION_BADGES.get(validation['status'], validation['status'])}**")
        for issue in validation.get("issues") or []:
            icon = ISSUE_ICONS.get(issue["level"], "•")
            st.markdown(f"{icon} `{issue['rule']}` - {issue['message']}")

    st.divider()
    st.subheader("Edit extracted fields")

    fields_json = st.text_area(
        "Fields (editable JSON)",
        value=json.dumps(extracted_data["extracted_fields"], indent=2),
        height=300,
    )

    col1, col2, col3, col4 = st.columns(4)

    if col1.button("💾 Save corrections"):
        try:
            new_fields = json.loads(fields_json)
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON: {exc}")
        else:
            result, error = patch(f"/documents/{document_id}/fields", json_body={"fields": new_fields})
            if not show_error(error):
                st.success("Fields updated and re-validated.")
                st.rerun()

    if col2.button("✅ Approve"):
        result, error = post(f"/documents/{document_id}/approve")
        if not show_error(error):
            st.success("Document approved.")
            st.rerun()

    if col3.button("🔴 Reject"):
        result, error = post(f"/documents/{document_id}/reject")
        if not show_error(error):
            st.warning("Document rejected.")
            st.rerun()

    if col4.button("↩️ Needs correction"):
        result, error = post(f"/documents/{document_id}/request-correction")
        if not show_error(error):
            st.info("Sent back for correction.")
            st.rerun()


# ---------------------------------------------------------------------------
# Page: Validation Results
# ---------------------------------------------------------------------------

def page_validation_results():
    st.title("🧪 Validation Results")

    documents, error = get("/documents", params={"limit": 200})
    if show_error(error):
        return

    rows = []
    for doc in documents:
        validation, verr = get(f"/documents/{doc['id']}/validation")
        if verr or not validation:
            continue
        for issue in validation.get("issues") or []:
            rows.append(
                {
                    "Document": f"#{doc['id']} {doc['filename']}",
                    "Level": issue["level"],
                    "Rule": issue["rule"],
                    "Field": issue.get("field") or "-",
                    "Message": issue["message"],
                }
            )

    if not rows:
        st.info("No validation issues recorded yet.")
        return

    level_filter = st.multiselect(
        "Filter by level", options=["error", "warning", "info"], default=["error", "warning", "info"]
    )
    filtered = [r for r in rows if r["Level"] in level_filter]

    st.dataframe(filtered, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page: Export
# ---------------------------------------------------------------------------

def page_export():
    st.title("📦 Export")

    approved_docs, error = get("/documents", params={"status": "approved", "limit": 200})
    if show_error(error):
        return

    if not approved_docs:
        st.info("No approved documents yet. Approve documents in **Review & Edit** first.")
    else:
        st.subheader("Approved documents ready to export")
        options = {doc_label(d): d["id"] for d in approved_docs}
        selected = st.multiselect("Select document(s) to export", list(options.keys()), default=list(options.keys()))
        selected_ids = [options[label] for label in selected]

        col1, col2 = st.columns(2)
        if col1.button("⬇️ Export selected as CSV", disabled=not selected_ids):
            result, error = post("/export/csv", json_body={"document_ids": selected_ids})
            if not show_error(error):
                st.success(result["message"])
                log = result["export_log"]
                st.markdown(download_link_markdown("Download CSV", log["id"], "csv"))

        if col2.button("⬇️ Export selected as JSON", disabled=not selected_ids):
            result, error = post("/export/json", json_body={"document_ids": selected_ids})
            if not show_error(error):
                st.success(result["message"])
                log = result["export_log"]
                st.markdown(download_link_markdown("Download JSON", log["id"], "json"))

    st.divider()
    st.subheader("Export history")
    logs, error = get("/export-logs", params={"limit": 100})
    if show_error(error):
        return
    if not logs:
        st.caption("No exports yet.")
        return

    rows = [
        {
            "Document ID": log["document_id"],
            "Type": log["export_type"].upper(),
            "Status": log["export_status"],
            "Exported at": fmt_dt(log["export_time"]),
            "Download": file_url(f"/export/download/{log['id']}"),
        }
        for log in logs
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page: Audit Logs
# ---------------------------------------------------------------------------

def page_audit_logs():
    st.title("🧾 Audit Logs")
    st.caption("Answers: what happened, when, and why?")

    logs, error = get("/audit-logs", params={"limit": 500})
    if show_error(error):
        return
    if not logs:
        st.info("No audit events yet.")
        return

    event_types = sorted({log["event_type"] for log in logs})
    selected_types = st.multiselect("Filter by event type", options=event_types, default=event_types)

    rows = []
    for log in logs:
        if log["event_type"] not in selected_types:
            continue
        rows.append(
            {
                "Time": fmt_dt(log["created_at"]),
                "Document": f"#{log['document_id']}" if log.get("document_id") else "",
                "Event": log["event_type"],
                "Actor": log["actor"],
                "Message": log["message"],
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page: Demo Mode
# ---------------------------------------------------------------------------

def page_demo_mode():
    st.title("🧪 Demo Mode")
    st.caption(
        "Load sample documents covering every scenario: a clean invoice, an "
        "invoice with a total mismatch, an invoice missing its due date, a "
        "receipt, a purchase order, and a contract."
    )

    if st.button("📥 Load Sample Documents", type="primary"):
        result, error = post("/demo/seed")
        if not show_error(error):
            if result:
                st.success(f"Seeded {len(result)} new sample document(s).")
            else:
                st.info("All sample documents were already seeded.")
            st.rerun()

    st.divider()
    st.subheader("What each sample demonstrates")
    st.markdown(
        "- **invoice_clean.pdf** - normal success flow, validates cleanly.\n"
        "- **invoice_wrong_total.pdf** - total does not match subtotal + tax -> validation warning.\n"
        "- **invoice_missing_due_date.pdf** - due date missing -> validation warning.\n"
        "- **receipt_grab.pdf** - receipt extraction.\n"
        "- **purchase_order.pdf** - purchase order workflow.\n"
        "- **service_agreement.pdf** - contract summary and risk extraction."
    )

    documents, error = get("/documents", params={"limit": 200})
    if not error and documents:
        demo_docs = [d for d in documents if d.get("is_demo")]
        if demo_docs:
            st.divider()
            st.subheader("Seeded demo documents")
            rows = [
                {
                    "ID": d["id"],
                    "Filename": d["filename"],
                    "Status": STATUS_BADGES.get(d["status"], d["status"]),
                }
                for d in demo_docs
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)
            st.caption("Open **Document Detail** to run each one through the pipeline.")


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

PAGES = {
    "Home": page_home,
    "Upload Document": page_upload,
    "Document List": page_document_list,
    "Document Detail": page_document_detail,
    "Review & Edit": page_review_edit,
    "Validation Results": page_validation_results,
    "Export": page_export,
    "Audit Logs": page_audit_logs,
    "Demo Mode": page_demo_mode,
}

st.sidebar.title("AI Document Automation")
selected_page = st.sidebar.radio("Navigate", list(PAGES.keys()))
st.sidebar.divider()
st.sidebar.caption(f"Backend API:\n`{API_BASE_URL}`")

PAGES[selected_page]()
