# playwright-mcp

Este MCP **no es código propio**: es el paquete oficial de Playwright
([`@playwright/mcp`](https://github.com/microsoft/playwright-mcp)), instalado
globalmente con npm. Por eso aquí solo se versiona la configuración, no el código.

## Instalación

```powershell
npm install -g @playwright/mcp@0.0.83
npx playwright install chromium
```

## Uso en OpenCode

Se conecta a un Chrome ya abierto con CDP (así reutiliza la sesión y las cookies
del navegador real):

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:TEMP\chrome-cdp"
```

```jsonc
{
  "mcp": {
    "playwright": {
      "type": "local",
      "command": [
        "node",
        "%APPDATA%/npm/node_modules/@playwright/mcp/cli.js",
        "--cdp-endpoint", "http://127.0.0.1:9222",
        "--output-dir", "%TEMP%/playwright-mcp"
      ]
    }
  }
}
```

Sin `--cdp-endpoint` Playwright lanza su propio navegador aislado (sin sesión).
