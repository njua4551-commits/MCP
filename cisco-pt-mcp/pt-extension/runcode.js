// ===== Script host: lo invoca el webview con $se("runCode", codigo) =====
// Ejecuta el código como cuerpo de función y devuelve SIEMPRE un sobre {success, result|error}.

function runCode(scriptText) {
  try {
    var fn = new Function(scriptText);
    var value = fn();
    // fuerza a JSON puro (sin objetos IPC vivos); si hay ciclos, lanza y se reporta como error
    var safe = (value === undefined) ? null : JSON.parse(JSON.stringify(value));
    return { success: true, result: safe };
  } catch (e) {
    return { success: false, error: (e && e.message) ? e.message : String(e), line: e && e.lineNumber };
  }
}
