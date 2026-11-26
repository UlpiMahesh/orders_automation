import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

PageBase {
    id: page
    title: "Convert orders"
    subtitle: "Turn a market's allocation workbook into a standard order file. Your original is never changed."
    signal navigate(int index)

    property string sourcePath: ""
    property string sourceName: ""
    property var sources: []
    property var result: ({})
    readonly property var market: backend.markets.find(function (m) { return m.id === backend.market }) || ({})

    function loadLatest() {
        var s = backend.latestSource(backend.market)
        sourcePath = s.path || ""; sourceName = s.name || ""
        sources = backend.sourceList(backend.market)
        result = ({})
    }
    function takeFile(url) {
        var r = backend.importSource(backend.market, url)
        if (r.ok) { sourcePath = r.path; sourceName = r.name; sources = backend.sourceList(backend.market) }
        else backend.toast(r.error, "warning")
    }
    Component.onCompleted: loadLatest()
    Connections {
        target: backend
        function onMarketChanged() { page.loadLatest() }
        function onTaskFinished(r) {
            if (r.action === "convert") { page.result = r.status === "success" ? r.result : ({}); page.sources = backend.sourceList(backend.market) }
        }
    }
    FileDialog {
        id: picker
        title: "Choose the " + backend.market + " workbook"
        nameFilters: ["Excel workbooks (*.xlsx *.xlsm)"]
        onAccepted: page.takeFile(selectedFile.toString())
    }

    SectionTitle { text: "1  ·  Market" }
    MarketPicker { Layout.fillWidth: true; needs: "convert" }

    SectionTitle { text: "2  ·  Source workbook" }
    Card {
        Layout.fillWidth: true
        padding: 18
        ColumnLayout {
            width: parent.width; spacing: 14
            Rectangle {
                id: drop
                Layout.fillWidth: true; Layout.preferredHeight: 116
                radius: 14; color: dropArea.containsDrag ? Qt.rgba(0.49, 0.36, 1, 0.16) : Theme.field
                border.width: 2; border.color: dropArea.containsDrag ? Theme.accent : Theme.border
                Behavior on color { ColorAnimation { duration: Theme.fast } }
                DropArea {
                    id: dropArea; anchors.fill: parent
                    onDropped: function (drop) { if (drop.hasUrls) page.takeFile(drop.urls[0].toString()) }
                }
                RowLayout {
                    anchors.fill: parent; anchors.margins: 22; spacing: 18
                    Text { text: page.sourcePath !== "" ? "▦" : "⇪"; color: Theme.accent2; font.pixelSize: 38 }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 3
                        Text {
                            text: page.sourcePath !== "" ? page.sourceName : "Drop the " + backend.market + " Excel file here"
                            color: Theme.text; font.family: Theme.sans; font.pixelSize: 17; font.weight: Font.DemiBold
                            elide: Text.ElideMiddle; Layout.fillWidth: true
                        }
                        Text {
                            text: page.sourcePath !== "" ? "Ready to convert. Drop another file to replace it." : "or use Browse. A copy is stored safely in your workspace."
                            color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13
                        }
                    }
                    AppButton { text: "Browse…"; kind: "secondary"; glyph: "📂"; onClicked: picker.open() }
                }
            }
            Flow {
                Layout.fillWidth: true; spacing: 8; visible: page.sources.length > 1
                Text { text: "Earlier files:"; color: Theme.dim; font.family: Theme.sans; font.pixelSize: 12; height: 30; verticalAlignment: Text.AlignVCenter }
                Repeater {
                    model: page.sources.slice(0, 5)
                    delegate: Chip {
                        required property var modelData
                        text: modelData.name.length > 38 ? modelData.name.substring(0, 36) + "…" : modelData.name
                        sub: modelData.modified
                        implicitHeight: 30
                        selected: page.sourcePath === modelData.path
                        onClicked: { page.sourcePath = modelData.path; page.sourceName = modelData.name }
                    }
                }
            }
        }
    }

    SectionTitle { text: "3  ·  Order date" }
    RowLayout {
        spacing: 10
        Field { id: dateField; Layout.preferredWidth: 190; mono: true; text: backend.todayIso(); placeholder: "YYYY-MM-DD" }
        AppButton { text: "Today"; kind: "secondary"; onClicked: dateField.text = backend.todayIso() }
        Text { text: "Used in the order reference names (e.g. 24NOV26…)"; color: Theme.dim; font.family: Theme.sans; font.pixelSize: 12; Layout.leftMargin: 6 }
    }

    AppButton {
        Layout.topMargin: 4
        text: "Convert orders"; glyph: "⇄"; big: true
        busy: backend.busy && backend.taskAction === "convert"
        enabledState: !backend.busy && page.sourcePath !== "" && !!page.market.canConvert
        onClicked: backend.convertOrders(backend.market, page.sourcePath, dateField.text)
    }

    // ---- result
    Card {
        Layout.fillWidth: true
        visible: page.result.output !== undefined
        border.color: Theme.ok
        ColumnLayout {
            width: parent.width; spacing: 16
            RowLayout {
                spacing: 12
                Text { text: "✔"; color: Theme.ok; font.pixelSize: 24 }
                Text { text: "Conversion complete"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 20; font.weight: Font.Bold }
            }
            RowLayout {
                spacing: 12
                StatTile { value: page.result.orders !== undefined ? page.result.orders : 0; caption: "orders" }
                StatTile { value: page.result.lines !== undefined ? page.result.lines : 0; caption: "lines" }
                StatTile { value: page.result.devices !== undefined ? page.result.devices : 0; caption: "devices" }
                StatTile {
                    property int notes: page.result.checks ? page.result.checks.filter(function (c) { return c.type !== "SUMMARY" }).length : 0
                    value: notes; caption: "notes to review"; tone: notes > 0 ? Theme.warn : Theme.ok
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 6
                visible: page.result.checks !== undefined && page.result.checks.filter(function (c) { return c.type !== "SUMMARY" }).length > 0
                Text { text: "Notes from the converter"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13; font.weight: Font.DemiBold }
                Repeater {
                    model: page.result.checks ? page.result.checks.filter(function (c) { return c.type !== "SUMMARY" }).slice(0, 8) : []
                    delegate: Text {
                        required property var modelData
                        Layout.fillWidth: true; wrapMode: Text.WordWrap
                        text: "•  " + modelData.type.toLowerCase() + " — " + modelData.detail
                        color: Theme.warn; font.family: Theme.sans; font.pixelSize: 12
                    }
                }
            }
            RowLayout {
                spacing: 10
                AppButton { text: "Check these orders"; glyph: "✔"; onClicked: page.navigate(2) }
                AppButton { text: "Open file"; kind: "secondary"; onClicked: backend.openPath(page.result.output) }
                AppButton { text: "Show in folder"; kind: "secondary"; onClicked: backend.revealPath(page.result.output) }
            }
        }
    }

    ConsolePanel {
        Layout.fillWidth: true; Layout.preferredHeight: 300
        visible: backend.busy || backend.logModel.count > 0
        title: "CONVERSION LOG"
    }
}
