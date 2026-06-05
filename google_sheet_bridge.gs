function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents || "{}");
    var secret = PropertiesService.getScriptProperties().getProperty("SHARED_SECRET") || "";
    if (secret && body.secret !== secret) {
      return jsonResponse({ success: false, error: "Invalid shared secret" });
    }

    var spreadsheetId = body.sheet_id;
    var action = body.action;
    var payload = body.payload || {};
    var ss = SpreadsheetApp.openById(spreadsheetId);

    if (action === "upsert_symbol") {
      upsertSymbol(ss, payload.symbol);
      return jsonResponse({ success: true });
    }

    if (action === "deactivate_symbol") {
      deactivateSymbol(ss, payload.symbol);
      return jsonResponse({ success: true });
    }

    if (action === "upsert_sim_position") {
      upsertSimPosition(ss, payload);
      return jsonResponse({ success: true });
    }

    if (action === "deactivate_sim_position") {
      deactivateSimPosition(ss, payload.symbol);
      return jsonResponse({ success: true });
    }

    return jsonResponse({ success: false, error: "Unsupported action: " + action });
  } catch (error) {
    return jsonResponse({ success: false, error: String(error) });
  }
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function todayIso() {
  return Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd");
}

function nowIso() {
  return Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm:ss");
}

function findRowBySymbol(sheet, symbol) {
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return -1;
  var values = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
  for (var i = 0; i < values.length; i++) {
    if (String(values[i][0]).toUpperCase().trim() === symbol) {
      return i + 2;
    }
  }
  return -1;
}

function appendAudit(ss, action, tableName, symbol, oldValue, newValue, notes) {
  var sheet = ss.getSheetByName("audit_log");
  if (!sheet) return;
  sheet.appendRow([
    nowIso(),
    action,
    tableName,
    symbol || "",
    oldValue || "",
    newValue || "",
    "apps_script",
    notes || ""
  ]);
}

function upsertSymbol(ss, symbol) {
  var sheet = ss.getSheetByName("symbols");
  var row = findRowBySymbol(sheet, symbol);
  if (row > 0) {
    var existing = sheet.getRange(row, 1, 1, 4).getValues()[0];
    var updated = [symbol, true, existing[2] || todayIso(), existing[3] || ""];
    sheet.getRange(row, 1, 1, 4).setValues([updated]);
    appendAudit(ss, "upsert", "symbols", symbol, JSON.stringify(existing), JSON.stringify(updated), "");
    return;
  }

  var inserted = [symbol, true, todayIso(), ""];
  sheet.appendRow(inserted);
  appendAudit(ss, "insert", "symbols", symbol, "", JSON.stringify(inserted), "");
}

function deactivateSymbol(ss, symbol) {
  var sheet = ss.getSheetByName("symbols");
  var row = findRowBySymbol(sheet, symbol);
  if (row < 0) {
    throw new Error(symbol + " not found");
  }
  var existing = sheet.getRange(row, 1, 1, 4).getValues()[0];
  var updated = [symbol, false, existing[2] || "", existing[3] || ""];
  sheet.getRange(row, 1, 1, 4).setValues([updated]);
  appendAudit(ss, "deactivate", "symbols", symbol, JSON.stringify(existing), JSON.stringify(updated), "");
}

function upsertSimPosition(ss, payload) {
  var symbol = String(payload.symbol || "").toUpperCase().trim();
  var sheet = ss.getSheetByName("sim_positions");
  var row = findRowBySymbol(sheet, symbol);
  var updated = [symbol, payload.shares, payload.cost, payload.buy_date, true, todayIso()];

  if (row > 0) {
    var existing = sheet.getRange(row, 1, 1, 6).getValues()[0];
    sheet.getRange(row, 1, 1, 6).setValues([updated]);
    appendAudit(ss, "upsert", "sim_positions", symbol, JSON.stringify(existing), JSON.stringify(updated), "");
    return;
  }

  sheet.appendRow(updated);
  appendAudit(ss, "insert", "sim_positions", symbol, "", JSON.stringify(updated), "");
}

function deactivateSimPosition(ss, symbol) {
  var sheet = ss.getSheetByName("sim_positions");
  var row = findRowBySymbol(sheet, symbol);
  if (row < 0) {
    throw new Error(symbol + " not found");
  }
  var existing = sheet.getRange(row, 1, 1, 6).getValues()[0];
  var updated = [symbol, existing[1], existing[2], existing[3], false, todayIso()];
  sheet.getRange(row, 1, 1, 6).setValues([updated]);
  appendAudit(ss, "deactivate", "sim_positions", symbol, JSON.stringify(existing), JSON.stringify(updated), "");
}
