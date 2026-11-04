// ===== Script host de Packet Tracer (tiene el objeto global `ipc`) =====
// Añade "MCP Bridge" al menú Extensions y abre el webview que hace el polling al servidor MCP.

function mcpBridge() {
  this.menuUuid = "";
  this.webview = null;
  this.webviewId = "";
}

mcpBridge.prototype.init = function () {
  var menu = ipc.appWindow().getMenuBar().getExtensionsPopupMenu();
  this.menuUuid = menu.insertItem("", "MCP Bridge");
  var item = menu.getMenuItemByUuid(this.menuUuid);
  item.registerEvent("onClicked", this, this.onMenu);
};

mcpBridge.prototype.onMenu = function () {
  this.show();
};

// Crea el webview (y con él empieza el polling) si no existe todavía.
mcpBridge.prototype.ensure = function () {
  if (this.webviewId == "" || webViewManager.getWebView(this.webviewId) == null) {
    this.webview = webViewManager.createWebView("MCP Bridge", "this-sm:bridge.html", 560, 440);
    this.webviewId = this.webview.getWebViewId();
    this.webview.registerEvent("closed", this, this.onClosed);
    return true;
  }
  return false;
};

mcpBridge.prototype.show = function () {
  this.ensure();
  this.webview.hide();   // hide()/show() fuerza a PT a traer la ventana al frente
  this.webview.show();
};

mcpBridge.prototype.onClosed = function () {
  this.webviewId = "";
  this.webview.unregisterEvent("closed", this, this.onClosed);
};

mcpBridge.prototype.cleanUp = function () {
  if (this.menuUuid != "") {
    var menu = ipc.appWindow().getMenuBar().getExtensionsPopupMenu();
    _ScriptModule.unregisterIpcEventByID("MenuItem", this.menuUuid, "onClicked", this, this.onMenu);
    menu.removeItemUuid(this.menuUuid);
    this.menuUuid = "";
  }
};

function main() {
  bridge = new mcpBridge();
  bridge.init();
  // Arranca el bridge oculto al abrir PT/el .pkt: se autoconecta; la ventana se ve en Extensions > MCP Bridge.
  if (bridge.ensure()) bridge.webview.hide();
}

function cleanUp() {
  bridge.cleanUp();
}
