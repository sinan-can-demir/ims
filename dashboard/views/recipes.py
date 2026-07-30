# dashboard/views/recipes.py
#
# Manage a dish's recipe/BOM — which ingredients it consumes, and how
# much, when it's sold (see app/services/inventory_service.py's
# _cascade_recipe_consumption). Routed via st.navigation()/st.Page() in
# dashboard/app.py — page_config and the auth gate happen once there,
# not per-page; require_login() here is a cheap no-op safety net for
# running this file standalone (dev, tests), not the real gate.

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.exceptions import DomainError
from dashboard.auth import require_login
from dashboard.data import load_products, load_recipe_items
from dashboard.recipe_actions import add_recipe_item, remove_recipe_item, update_recipe_item

current_user = require_login()

st.title("🍳 Recipes / BOM")
st.caption(
    "Define what a dish consumes when it's sold. Selling a dish automatically "
    "decrements its ingredients' stock by the quantities below, atomically with "
    "the sale itself."
)

products = load_products(current_user["organization_id"])
if not products:
    st.info("No products yet — create some via the API first.")
    st.stop()

product_labels = {p["id"]: f"{p['name']} ({p['sku']})" for p in products}

col_select, col_refresh = st.columns([5, 1])
with col_select:
    selected_dish_id = st.selectbox(
        "Dish", options=list(product_labels.keys()), format_func=lambda pid: product_labels[pid]
    )
with col_refresh:
    st.write("")
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

st.divider()
st.subheader("Current recipe")

recipe_items = load_recipe_items(selected_dish_id)

if recipe_items:
    header_name, header_qty, header_update, header_delete = st.columns([3, 2, 2, 1])
    header_name.markdown("**Ingredient**")
    header_qty.markdown("**Qty per dish**")

    for item in recipe_items:
        col_name, col_qty, col_update, col_delete = st.columns([3, 2, 2, 1])

        component_id = item["component_product_id"]
        with col_name:
            st.write(product_labels.get(component_id, f"Product {component_id}"))

        with col_qty:
            new_qty = st.number_input(
                "Quantity",
                min_value=1,
                value=item["quantity"],
                key=f"qty-{item['id']}",
                label_visibility="collapsed",
            )

        with col_update:
            if st.button("Update", key=f"update-{item['id']}"):
                try:
                    update_recipe_item(item["id"], int(new_qty))
                except DomainError as e:
                    st.error(str(e))
                else:
                    st.cache_data.clear()
                    st.rerun()

        with col_delete:
            if st.button("🗑️", key=f"delete-{item['id']}"):
                try:
                    remove_recipe_item(item["id"])
                except DomainError as e:
                    st.error(str(e))
                else:
                    st.cache_data.clear()
                    st.rerun()
else:
    st.info("This dish has no recipe yet — selling it won't consume any other product.")

st.divider()
st.subheader("Add ingredient")

other_products = [p for p in products if p["id"] != selected_dish_id]

if not other_products:
    st.info("No other products exist to use as an ingredient yet.")
else:
    with st.form("add_recipe_item_form", clear_on_submit=True):
        component_id = st.selectbox(
            "Ingredient",
            options=[p["id"] for p in other_products],
            format_func=lambda pid: product_labels[pid],
        )
        quantity = st.number_input("Quantity per dish sold", min_value=1, value=1)
        submitted = st.form_submit_button("Add ingredient")

    if submitted:
        try:
            add_recipe_item(selected_dish_id, component_id, int(quantity))
        except DomainError as e:
            st.error(str(e))
        else:
            st.cache_data.clear()
            st.rerun()
