"""
WooCommerce Search Tool.
Native integration to search products in WooCommerce.
Requires the agent to have WooCommerce enabled and configured.
"""
import httpx
from openacm.tools.base import tool
from openacm.web.state import _state as state

import re

@tool(
    name="woocommerce_search",
    description=(
        "Search for products in the store's inventory (WooCommerce). "
        "Returns product names, prices, stock status, links, and detailed specifications. "
        "Use this ONLY when the user asks for product availability, prices, or details."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The product name or keyword to search for",
            }
        },
        "required": ["query"],
    },
    risk_level="low",
    category="ecommerce",
)
async def woocommerce_search(query: str, _brain=None, **kwargs) -> str:
    """Search products in WooCommerce using the agent's configuration."""
    if not _brain or not hasattr(_brain, "agent_id"):
        return "Error: Tool requires agent context but none was provided."
    
    if not state.database:
        return "Error: Database is not available."

    agent = await state.database.get_agent(_brain.agent_id)
    if not agent:
        return "Error: Agent not found."

    if not agent.get("woo_enabled"):
        return "System Notification: WooCommerce integration is disabled for this agent. Tell the user you cannot search the store right now."

    woo_url = agent.get("woo_url", "").strip()
    woo_ck = agent.get("woo_ck", "").strip()
    woo_cs = agent.get("woo_cs", "").strip()

    if not woo_url or not woo_ck or not woo_cs:
        return "System Notification: WooCommerce integration is enabled but missing configuration (URL or Keys). Tell the admin to configure it in the dashboard."

    # Ensure URL formatting
    if not woo_url.endswith("/wp-json/wc/v3/products"):
        if woo_url.endswith("/"):
            woo_url += "wp-json/wc/v3/products"
        else:
            woo_url += "/wp-json/wc/v3/products"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                woo_url,
                params={"search": query},
                auth=(woo_ck, woo_cs)
            )
            response.raise_for_status()
            products = response.json()

            if not products:
                return f"No products found for query: '{query}'."

            output = [f"Search results for '{query}':"]
            for p in products[:5]:  # Limit to top 5
                stock = p.get('stock_quantity')
                stock_text = str(stock) if stock is not None else ('In stock' if p.get('manage_stock') == False else 'Out of stock')
                
                # Extract description and strip HTML
                raw_desc = p.get('short_description', '')
                if not raw_desc:
                    raw_desc = p.get('description', '')
                clean_desc = re.sub(r'<[^>]+>', ' ', raw_desc).strip()
                clean_desc = re.sub(r'\s+', ' ', clean_desc)  # clean up multiple spaces
                
                output.append(f"- Product: {p.get('name')}")
                output.append(f"  Price: ${p.get('price')}")
                output.append(f"  Stock: {stock_text}")
                if clean_desc:
                    # Truncate description to 300 characters so we don't overload context
                    shortened = clean_desc[:300] + "..." if len(clean_desc) > 300 else clean_desc
                    output.append(f"  Description: {shortened}")
                output.append(f"  Link: {p.get('permalink')}")
            
            return "\n".join(output)

    except httpx.HTTPError as e:
        return f"Error communicating with WooCommerce API: {str(e)}"
    except Exception as e:
        return f"Unexpected error searching WooCommerce: {str(e)}"
