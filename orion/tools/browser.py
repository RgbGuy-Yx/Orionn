"""
Browser and desktop control tools — web search, app launching, and website navigation.
"""

import webbrowser
import subprocess
import urllib.parse
import logging
import platform

logger = logging.getLogger("orion-browser-tools")

# App mapping for Windows — maps user-friendly names to executable paths or commands
APP_MAPPING = {
    "chrome": "chrome",
    "edge": "msedge",
    "firefox": "firefox",
    "vscode": "code",
    "vs code": "code",
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "spotify": "spotify",
    "discord": "discord",
    "slack": "slack",
    "teams": "teams",
}


def register(mcp):
    """Register all browser and desktop control tools with the MCP server."""

    @mcp.tool()
    async def search_google(query: str) -> str:
        """
        Search Google for a query and open results in the default browser.
        
        Args:
            query: The search query (e.g., "python web scraping")
        
        Returns:
            Confirmation message with the search URL
        """
        if not query or not query.strip():
            return "Search query cannot be empty, boss."
        
        try:
            encoded_query = urllib.parse.quote(query)
            url = f"https://www.google.com/search?q={encoded_query}"
            webbrowser.open(url)
            logger.info(f"Opened Google search for: {query}")
            return f"Searching Google for '{query}'. Pulling that up for you now, sir."
        except Exception as e:
            logger.error(f"Failed to search Google: {e}")
            return f"Unable to search Google right now, boss: {str(e)}"

    @mcp.tool()
    async def search_youtube(query: str) -> str:
        """
        Search YouTube for a query and open results in the default browser.
        
        Args:
            query: The search query (e.g., "tony stark suit up scene")
        
        Returns:
            Confirmation message with the search URL
        """
        if not query or not query.strip():
            return "Search query cannot be empty, boss."
        
        try:
            encoded_query = urllib.parse.quote(query)
            url = f"https://www.youtube.com/results?search_query={encoded_query}"
            webbrowser.open(url)
            logger.info(f"Opened YouTube search for: {query}")
            return f"Searching YouTube for '{query}'. Loading the results now, sir."
        except Exception as e:
            logger.error(f"Failed to search YouTube: {e}")
            return f"Unable to search YouTube right now, boss: {str(e)}"

    @mcp.tool()
    async def open_website(url: str) -> str:
        """
        Open a website in the default browser.
        
        Args:
            url: The website URL (e.g., "https://example.com" or "example.com")
        
        Returns:
            Confirmation message or error
        """
        if not url or not url.strip():
            return "URL cannot be empty, boss."
        
        try:
            # Ensure URL has a scheme
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"
            
            webbrowser.open(url)
            logger.info(f"Opened website: {url}")
            return f"Opening {url} for you now, sir."
        except Exception as e:
            logger.error(f"Failed to open website {url}: {e}")
            return f"Unable to open that website, boss: {str(e)}"

    @mcp.tool()
    async def open_app(app_name: str) -> str:
        """
        Launch an application on the desktop.
        
        Supported apps (Windows):
        - chrome, edge, firefox
        - vscode (vs code)
        - notepad
        - calculator
        - spotify, discord, slack, teams
        
        Args:
            app_name: The name of the app to launch (e.g., "chrome", "vscode")
        
        Returns:
            Confirmation message or error
        """
        if not app_name or not app_name.strip():
            return "App name cannot be empty, boss."
        
        app_name_lower = app_name.lower().strip()
        
        # Check if the app is in our mapping
        if app_name_lower not in APP_MAPPING:
            available = ", ".join(sorted(APP_MAPPING.keys()))
            return f"Unknown app '{app_name}'. Available apps: {available}"
        
        executable = APP_MAPPING[app_name_lower]
        
        try:
            if platform.system() == "Windows":
                # Use subprocess to launch the app on Windows
                subprocess.Popen(executable, shell=True)
            else:
                # Fallback for other systems
                subprocess.Popen([executable])
            
            logger.info(f"Launched app: {app_name}")
            return f"Launching {app_name} now, sir."
        except FileNotFoundError:
            logger.error(f"App not found: {executable}")
            return f"I couldn't find '{app_name}' on this system, boss. Make sure it's installed."
        except Exception as e:
            logger.error(f"Failed to launch {app_name}: {e}")
            return f"Unable to launch {app_name}, boss: {str(e)}"
