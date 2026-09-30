"""The eight production formats and their OpenArt content choices."""

FORMATS = {
    "line": "Line, then card",
    "card": "Card only",
    "compare": "Tick and cross",
    "farm": "Content farm",
    "mcp_farm": "MCP content farm",
    "reaction": "Hook Story",
    "tutorial_story": "Bottle spin",
    "ai_larp": "AI LARP",
}
PRODUCTS = {"mcp": "MCP", "chat": "Chat", "director": "Director"}
PRODUCT_FORMATS = {
    "mcp": ("line", "card", "compare", "farm", "mcp_farm", "reaction"),
    "chat": ("farm", "reaction"),
    "director": ("farm", "reaction", "tutorial_story", "ai_larp"),
}


def formats(product):
    if product not in PRODUCTS:
        raise ValueError("Choose MCP, Chat or Director.")
    return PRODUCT_FORMATS[product]


def require(fmt, product):
    if fmt not in formats(product):
        raise ValueError("Choose a format available for " + PRODUCTS[product] + ".")
