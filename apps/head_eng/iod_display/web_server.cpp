#include "web_server.h"
#include "status_protocol.h"

namespace hv {

String WebStatusServer::htmlTemplate() {
  return F(
      "<!doctype html><html><head><meta charset='utf-8'>"
      "<meta name='viewport' content='width=device-width,initial-scale=1'>"
      "<title>Head Monitor</title>"
      "<style>body{font-family:Arial,sans-serif;background:#111;color:#eee;margin:0;padding:16px}"
      ".card{max-width:680px;margin:0 auto;background:#1b1b1b;border:1px solid #333;padding:12px;border-radius:8px}"
      "h2{margin:0 0 10px 0} .row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #2a2a2a}"
      ".k{color:#9aa0a6}.ok{color:#7bd88f}.bad{color:#ff6b6b}</style></head><body>"
      "<div class='card'><h2>Pico Head Status</h2><div id='rows'></div></div>"
      "<script>async function tick(){try{const r=await fetch('/api/status');const j=await r.json();"
      "const s=j.stale?'bad':'ok';const rows=["
      "['Comms',j.stale?'STALE':'OK',s],['LastError',j.last_error||''],['IP',j.ip],['Mask',j.mask],['Gateway',j.gateway],"
      "['Mode',j.network_mode],['Link',j.link],['VMain',j.v_main],['VAux',j.v_aux],['Age(ms)',String(j.age_ms)],"
      "['PollOK',String(j.ok_count)],['PollErr',String(j.err_count)]"
      "];const el=document.getElementById('rows');"
      "el.innerHTML=rows.map(r=>`<div class='row'><div class='k'>${r[0]}</div><div class='${r[2]||''}'>${r[1]}</div></div>`).join('');"
      "}catch(e){document.getElementById('rows').innerHTML='<div class=\"row\"><div class=\"bad\">API error</div></div>';}}"
      "tick();setInterval(tick,2000);</script></body></html>");
}

String WebStatusServer::jsonStatus() const {
  RuntimeStatus empty;
  const RuntimeStatus& s = state_ ? *state_ : empty;
  const uint32_t nowMs = millis();
  const String ip = s.hasFrame ? ipv4ToString(s.frame.ip) : "N/A";
  const String mask = s.hasFrame ? ipv4ToString(s.frame.mask) : "N/A";
  const String gw = s.hasFrame ? ipv4ToString(s.frame.gateway) : "N/A";
  const String mode = networkModeText(s);
  const String link = linkText(s);
  const String vMain = s.hasFrame ? voltageText(s.frame.vMainMv) : "N/A";
  const String vAux = s.hasFrame ? voltageText(s.frame.vAuxMv) : "N/A";
  const uint32_t age = ageMs(s, nowMs);

  String out = "{";
  out += "\"stale\":";
  out += (s.stale ? "true" : "false");
  out += ",\"last_error\":\"";
  out += s.lastError;
  out += "\",\"ip\":\"";
  out += ip;
  out += "\",\"mask\":\"";
  out += mask;
  out += "\",\"gateway\":\"";
  out += gw;
  out += "\",\"network_mode\":\"";
  out += mode;
  out += "\",\"link\":\"";
  out += link;
  out += "\",\"v_main\":\"";
  out += vMain;
  out += "\",\"v_aux\":\"";
  out += vAux;
  out += "\",\"age_ms\":";
  out += (age == UINT32_MAX ? String(-1) : String(age));
  out += ",\"ok_count\":";
  out += String(s.okCount);
  out += ",\"err_count\":";
  out += String(s.errCount);
  out += "}";
  return out;
}

void WebStatusServer::begin(const RuntimeStatus* state) {
  state_ = state;
  server_.on("/", HTTP_GET, [this]() { server_.send(200, "text/html", htmlTemplate()); });
  server_.on("/api/status", HTTP_GET, [this]() { server_.send(200, "application/json", jsonStatus()); });
  server_.onNotFound([this]() { server_.send(404, "text/plain", "not found"); });
  server_.begin();
}

void WebStatusServer::loop() {
  server_.handleClient();
}

}  // namespace hv
