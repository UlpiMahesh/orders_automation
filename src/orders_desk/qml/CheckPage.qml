import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

PageBase {
    id: page
    title: "Check orders"
    subtitle: "See exactly what would be ordered — store by store — and catch problems before anything is placed."
    signal navigate(int index)

    property var workbooks: []
    property string workbookPath: ""
    property var report: ({})
    property var expanded: ({})
    readonly property var notes: report.checks ? report.checks.filter(function (c) { return c.type !== "SUMMARY" }) : []

    function reload() {
        workbooks = backend.convertedList(backend.market)
        workbookPath = workbooks.length ? workbooks[0].path : ""
        report = ({}); expanded = ({})
    }
    function toggle(ref) { var e = Object.assign({}, expanded); e[ref] = !e[ref]; expanded = e }
    Component.onCompleted: reload()
    Connections {
        target: backend
        function onMarketChanged() { page.reload() }
        function onFilesChanged() { var keep = page.workbookPath; page.workbooks = backend.convertedList(backend.market)
                                    if (keep === "" && page.workbooks.length) page.workbookPath = page.workbooks[0].path }
        function onTaskFinished(r) {
            if (r.action === "check" && r.result && r.result.task === "check") page.report = r.result
            if (r.action === "convert" && r.status === "success") { page.workbooks = backend.convertedList(backend.market)
                                                                    page.workbookPath = page.workbooks.length ? page.workbooks[0].path : ""; page.report = ({}) }
        }
    }

    SectionTitle { text: "1  ·  Market" }
    MarketPicker { Layout.fillWidth: true; needs: "place" }

    SectionTitle { text: "2  ·  Converted workbook" }
    Flow {
        Layout.fillWidth: true; spacing: 8
        Repeater {
            model: page.workbooks.slice(0, 6)
            delegate: Chip {
                required property var modelData
                text: modelData.name; sub: modelData.modified
                selected: page.workbookPath === modelData.path
                onClicked: { page.workbookPath = modelData.path; page.report = ({}) }
            }
        }
        Text { visible: page.workbooks.length === 0; text: "No converted workbook for " + backend.market + " yet — run Convert orders first."
               color: Theme.warn; font.family: Theme.sans; font.pixelSize: 14 }
    }

    AppButton {
        text: "Check orders"; glyph: "✔"; big: true
        busy: backend.busy && backend.taskAction === "check"
        enabledState: !backend.busy && page.workbookPath !== ""
        onClicked: backend.checkOrders(backend.market, page.workbookPath)
    }

    Card {
        Layout.fillWidth: true
        visible: page.report.task === "check"
        border.color: page.report.ok ? Theme.ok : Theme.danger
        ColumnLayout {
            width: parent.width; spacing: 18
            RowLayout {
                spacing: 12
                Text { text: page.report.ok ? "✔" : "✖"; color: page.report.ok ? Theme.ok : Theme.danger; font.pixelSize: 24 }
                Text { text: page.report.ok ? "Ready to place" : "Needs attention before placing"; color: Theme.text
                       font.family: Theme.sans; font.pixelSize: 20; font.weight: Font.Bold }
            }
            RowLayout {
                spacing: 12
                StatTile { value: page.report.orders ? page.report.orders.length : 0; caption: "orders ready"; tone: Theme.ok }
                StatTile { value: page.report.rejected ? page.report.rejected.length : 0; caption: "rejected"; tone: (page.report.rejected && page.report.rejected.length) ? Theme.danger : Theme.text }
                StatTile {
                    value: { var t = 0; if (page.report.orders) for (var i = 0; i < page.report.orders.length; i++) t += page.report.orders[i].devices; return t }
                    caption: "devices"
                }
                StatTile { value: page.notes.length; caption: "converter notes"; tone: page.notes.length ? Theme.warn : Theme.text }
            }
            ColumnLayout {
                visible: page.report.rejected !== undefined && page.report.rejected.length > 0
                Layout.fillWidth: true; spacing: 6
                Text { text: "Rejected at planning"; color: Theme.danger; font.family: Theme.sans; font.pixelSize: 13; font.weight: Font.DemiBold }
                Repeater {
                    model: page.report.rejected ? page.report.rejected : []
                    delegate: Text { required property var modelData; Layout.fillWidth: true; wrapMode: Text.WordWrap
                                     text: "•  " + modelData.ref + " — " + modelData.reason; color: Theme.danger; font.family: Theme.sans; font.pixelSize: 12 }
                }
            }
            ColumnLayout {
                visible: page.notes.length > 0
                Layout.fillWidth: true; spacing: 6
                Text { text: "Converter notes — read these before placing (skipped or rounded items)"; color: Theme.warn; font.family: Theme.sans; font.pixelSize: 13; font.weight: Font.DemiBold }
                Repeater {
                    model: page.notes.slice(0, 10)
                    delegate: Text { required property var modelData; Layout.fillWidth: true; wrapMode: Text.WordWrap
                                     text: "•  " + modelData.type.toLowerCase() + " — " + modelData.detail; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 12 }
                }
            }
            // orders table
            ColumnLayout {
                Layout.fillWidth: true; spacing: 0
                Rectangle {
                    Layout.fillWidth: true; height: 34; color: Theme.field; radius: 8
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14; spacing: 10
                        Repeater {
                            model: [["Reference", 2.2], ["Store", 2.2], ["Ship", 1.1], ["Lines", 0.7], ["Units", 0.7], ["Devices", 0.9]]
                            delegate: Text { required property var modelData; text: modelData[0]; Layout.fillWidth: true; Layout.preferredWidth: modelData[1] * 40
                                             color: Theme.dim; font.family: Theme.sans; font.pixelSize: 12; font.weight: Font.Bold }
                        }
                    }
                }
                Repeater {
                    model: page.report.orders ? page.report.orders : []
                    delegate: Column {
                        required property var modelData
                        Layout.fillWidth: true
                        Rectangle {
                            width: parent.width; height: 44; color: rowMouse.containsMouse ? Theme.surfaceHi : "transparent"
                            RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14; spacing: 10
                                Text { text: (page.expanded[modelData.ref] ? "▾ " : "▸ ") + modelData.ref; Layout.fillWidth: true; Layout.preferredWidth: 88
                                       color: Theme.text; font.family: Theme.mono; font.pixelSize: 13; elide: Text.ElideRight }
                                Text { text: modelData.store; Layout.fillWidth: true; Layout.preferredWidth: 88; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13; elide: Text.ElideRight }
                                Text { text: modelData.shipping; Layout.fillWidth: true; Layout.preferredWidth: 44
                                       color: modelData.shipping === "OVERNIGHT" ? Theme.warn : Theme.muted; font.family: Theme.sans; font.pixelSize: 12; font.weight: Font.DemiBold }
                                Text { text: modelData.lineCount; Layout.fillWidth: true; Layout.preferredWidth: 28; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13 }
                                Text { text: modelData.units; Layout.fillWidth: true; Layout.preferredWidth: 28; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13 }
                                Text { text: modelData.devices + (modelData.cpo > 0 ? "  CPO" : ""); Layout.fillWidth: true; Layout.preferredWidth: 36; color: Theme.text; font.family: Theme.sans; font.pixelSize: 13 }
                            }
                            MouseArea { id: rowMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.toggle(modelData.ref) }
                            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border; opacity: 0.6 }
                        }
                        Column {
                            visible: !!page.expanded[modelData.ref]
                            width: parent.width
                            Text { width: parent.width; leftPadding: 32; topPadding: 8; bottomPadding: 6; text: modelData.address; color: Theme.dim; font.family: Theme.sans; font.pixelSize: 12 }
                            Repeater {
                                model: modelData.lines
                                delegate: Row {
                                    required property var modelData
                                    leftPadding: 32; spacing: 16; height: 26
                                    Text { text: modelData.sku; width: 120; color: Theme.dim; font.family: Theme.mono; font.pixelSize: 12 }
                                    Text { text: modelData.name; width: 330; elide: Text.ElideRight; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 12 }
                                    Text { text: modelData.qty + " " + modelData.unit; width: 70; color: Theme.text; font.family: Theme.sans; font.pixelSize: 12; font.weight: Font.DemiBold }
                                }
                            }
                            Item { width: 1; height: 8 }
                        }
                    }
                }
            }
            RowLayout {
                spacing: 10
                AppButton { text: "Continue to Place orders"; glyph: "➤"; visible: !!page.report.ok; onClicked: page.navigate(3) }
                AppButton { text: "Open the workbook"; kind: "secondary"; onClicked: backend.openPath(page.workbookPath) }
            }
        }
    }

    ConsolePanel {
        Layout.fillWidth: true; Layout.preferredHeight: 220
        visible: backend.busy && backend.taskAction === "check"
        title: "CHECK LOG"
    }
}
