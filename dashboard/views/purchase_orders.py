# dashboard/views/purchase_orders.py
#
# Manage suppliers and purchase orders: create a draft (manually or
# generated from a product's forecast/restock recommendation), submit it,
# then receive it — receiving creates real PURCHASE inventory events (see
# app/services/purchase_order_service.py). Routed via
# st.navigation()/st.Page() in dashboard/app.py — page_config and the
# auth gate happen once there, not per-page; require_login() here is a
# cheap no-op safety net for running this file standalone (dev, tests),
# not the real gate.

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.exceptions import DomainError
from dashboard.auth import require_login
from dashboard.data import load_products, load_purchase_orders, load_suppliers
from dashboard.po_actions import (
    add_line,
    add_supplier,
    create_po,
    generate_po,
    receive_po,
    submit_po,
)

current_user = require_login()

st.title("📦 Purchase Orders")

if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

products = load_products(current_user["organization_id"])
suppliers = load_suppliers(current_user["organization_id"])

if not products:
    st.info("No products yet — create some via the API first.")
    st.stop()

product_labels = {p["id"]: f"{p['name']} ({p['sku']})" for p in products}
supplier_labels = {s["id"]: s["name"] for s in suppliers}

# ---------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------
st.subheader("Suppliers")

if suppliers:
    st.dataframe(
        [{"Name": s["name"]} for s in suppliers], use_container_width=True, hide_index=True
    )
else:
    st.info("No suppliers yet — add one below.")

with st.form("add_supplier_form", clear_on_submit=True):
    col_name, col_email = st.columns(2)
    with col_name:
        supplier_name = st.text_input("Supplier name")
    with col_email:
        supplier_email = st.text_input("Contact email (optional)")
    submitted_supplier = st.form_submit_button("Add supplier")

if submitted_supplier:
    if not supplier_name:
        st.error("Supplier name is required.")
    else:
        try:
            add_supplier(supplier_name, supplier_email or None, current_user["organization_id"])
        except DomainError as e:
            st.error(str(e))
        else:
            st.cache_data.clear()
            st.rerun()

st.divider()

# ---------------------------------------------------------------
# Create a draft PO
# ---------------------------------------------------------------
st.subheader("Create a draft purchase order")

if not suppliers:
    st.info("Add a supplier above before creating a purchase order.")
else:
    col_generate, col_manual = st.columns(2)

    with col_generate:
        st.caption("Generate from this product's current forecast/restock recommendation.")
        gen_product_id = st.selectbox(
            "Product (from forecast)",
            options=list(product_labels.keys()),
            format_func=lambda pid: product_labels[pid],
            key="gen_product",
        )
        gen_supplier_id = st.selectbox(
            "Supplier (from forecast)",
            options=list(supplier_labels.keys()),
            format_func=lambda sid: supplier_labels[sid],
            key="gen_supplier",
        )
        if st.button("Generate from forecast"):
            try:
                generate_po(
                    gen_product_id,
                    gen_supplier_id,
                    current_user["id"],
                    current_user["organization_id"],
                )
            except DomainError as e:
                st.error(str(e))
            else:
                st.cache_data.clear()
                st.success("Draft purchase order created.")
                st.rerun()

    with col_manual:
        st.caption("Or create a draft manually with one line to start.")
        with st.form("create_po_form"):
            manual_product_id = st.selectbox(
                "Product (manual)",
                options=list(product_labels.keys()),
                format_func=lambda pid: product_labels[pid],
                key="manual_product",
            )
            manual_supplier_id = st.selectbox(
                "Supplier (manual)",
                options=list(supplier_labels.keys()),
                format_func=lambda sid: supplier_labels[sid],
                key="manual_supplier",
            )
            manual_quantity = st.number_input("Quantity", min_value=1, value=1)
            create_submitted = st.form_submit_button("Create draft")

        if create_submitted:
            try:
                create_po(
                    manual_supplier_id,
                    manual_product_id,
                    int(manual_quantity),
                    current_user["id"],
                    current_user["organization_id"],
                )
            except DomainError as e:
                st.error(str(e))
            else:
                st.cache_data.clear()
                st.success("Draft purchase order created.")
                st.rerun()

st.divider()

# ---------------------------------------------------------------
# PO list
# ---------------------------------------------------------------
st.subheader("Purchase orders")

status_filter = st.selectbox("Filter by status", options=["All", "DRAFT", "SUBMITTED", "RECEIVED"])
orders = load_purchase_orders(
    None if status_filter == "All" else status_filter, current_user["organization_id"]
)

if not orders:
    st.info("No purchase orders match this filter.")

for po in orders:
    supplier_name = supplier_labels.get(po["supplier_id"], f"Supplier {po['supplier_id']}")
    with st.expander(f"PO #{po['id']} — {supplier_name} — {po['status']} — {po['created_at']}"):
        line_rows = [
            {
                "Product": product_labels.get(line["product_id"], f"Product {line['product_id']}"),
                "Quantity": line["quantity"],
                "Unit cost": line["unit_cost"] if line["unit_cost"] is not None else "-",
            }
            for line in po["lines"]
        ]
        if line_rows:
            st.dataframe(line_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No lines yet.")

        if po["status"] == "DRAFT":
            with st.form(f"add_line_form_{po['id']}", clear_on_submit=True):
                col_product, col_qty, col_add = st.columns([3, 2, 1])
                with col_product:
                    line_product_id = st.selectbox(
                        "Add product",
                        options=list(product_labels.keys()),
                        format_func=lambda pid: product_labels[pid],
                        key=f"line_product_{po['id']}",
                        label_visibility="collapsed",
                    )
                with col_qty:
                    line_qty = st.number_input(
                        "Qty",
                        min_value=1,
                        value=1,
                        key=f"line_qty_{po['id']}",
                        label_visibility="collapsed",
                    )
                with col_add:
                    add_line_submitted = st.form_submit_button("Add line")

            if add_line_submitted:
                try:
                    add_line(
                        po["id"],
                        line_product_id,
                        int(line_qty),
                        current_user["organization_id"],
                    )
                except DomainError as e:
                    st.error(str(e))
                else:
                    st.cache_data.clear()
                    st.rerun()

            if st.button("Submit purchase order", key=f"submit_{po['id']}"):
                try:
                    submit_po(po["id"], current_user["id"], current_user["organization_id"])
                except DomainError as e:
                    st.error(str(e))
                else:
                    st.cache_data.clear()
                    st.rerun()

        elif po["status"] == "SUBMITTED":
            st.caption("Submitted — mark received once the shipment actually arrives.")
            if st.button("Mark received", key=f"receive_{po['id']}"):
                try:
                    receive_po(po["id"], current_user["id"], current_user["organization_id"])
                except DomainError as e:
                    st.error(str(e))
                else:
                    st.cache_data.clear()
                    st.success(f"PO #{po['id']} received — inventory updated.")
                    st.rerun()

        else:
            st.caption("Received — inventory already updated.")
