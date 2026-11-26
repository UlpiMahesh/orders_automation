import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

PageBase {
    id: page
    title: "Files & results"
    subtitle: "Everything the app produces lives in your workspace folder — outside the program. Open any of it from here."
    signal navigate(int index)

    property string marketFilter: ""
    property string categoryFilter: ""
    property var rows: []
    property var selected: ({})
    property var preview: ({ kind: "none" })

    function reload() {
        rows = backend.listFiles(marketFilter, categoryFilter, search.text)
        if (selected.path !== undefined && !rows.some(function (r) { return r.path === selected.path })) { selected = ({}); preview = ({ kind: "none" }) }
    }
    function select(row) { selected = row; preview = backend.previewFile(row.path) }
    Component.onCompleted: reload()
    onMarketFilterChanged: reload()
    onCategoryFilterChanged: reload()
    Connections { target: backend; function onFilesChanged() { page.reload() } }

    RowLayout {
        Layout.fillWidth: true; spacing: 10
        AppButton { text: "Open workspace folder"; glyph: "📂"; kind: "secondary"; onClicked: backend.openWorkspace() }
        Text { text: backend.workspacePath; color: Theme.dim; font.family: Theme.mono; font.pixelSize: 12; elide: Text.ElideMiddle; Layout.fillWidth: true }
    }

    Flow {
        Layout.fillWidth: true; spacing: 8
        Chip { text: "All markets"; selected: page.marketFilter === ""; onClicked: page.marketFilter = "" }
        Repeater {
            model: backend.markets.filter(function (m) { return m.canConvert })
            delegate: Chip { required property var modelData; text: modelData.id; selected: page.marketFilter === modelData.id; onClicked: page.marketFilter = modelData.id }
        }
    }
    Flow {
        Layout.fillWidth: true; spacing: 8
        Repeater {
            model: ["", "Source", "Converted", "Results", "Confirmations", "Logs", "Debug"]
            delegate: Chip { required property string modelData; text: modelData === "" ? "Everything" : modelData; selected: page.categoryFilter === modelData
                             onClicked: page.categoryFilter = modelData }
        }
    }
    Field { id: search; Layout.fillWidth: true; placeholder: "Search file names…"; onTextChanged: page.reload() }

    RowLayout {
        Layout.fillWidth: true; Layout.preferredHeight: 560; spacing: 16

        Card {
            Layout.fillWidth: true; Layout.fillHeight: true; padding: 6
            ListView {
                id: list
                anchors.fill: parent; clip: true
                model: page.rows
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { }
                delegate: Item {
                    id: row
                    required property var modelData
                    width: list.width; height: 54
                    readonly property bool isSel: page.selected.path === modelData.path
                    Rectangle { anchors.fill: parent; anchors.margins: 2; radius: 10
                                color: row.isSel ? Qt.rgba(0.49, 0.36, 1, 0.20) : (hover.containsMouse ? Theme.surfaceHi : "transparent") }
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 12; spacing: 12
                        Text { text: ({ xlsx: "▦", png: "▣", txt: "≣", log: "≣", html: "⌘", json: "≣" })[modelData.ext] || "▫"
                               color: Theme.accent2; font.pixelSize: 20; Layout.preferredWidth: 24 }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 1
                            Text { text: modelData.name; color: Theme.text; font.family: Theme.sans; font.pixelSize: 14; font.weight: Font.DemiBold; elide: Text.ElideMiddle; Layout.fillWidth: true }
                            Text { text: modelData.market + "  ·  " + modelData.category + "  ·  " + modelData.modified + "  ·  " + modelData.size
                                   color: Theme.dim; font.family: Theme.sans; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                        }
                    }
                    MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: page.select(modelData); onDoubleClicked: backend.openPath(modelData.path) }
                }
                Text { anchors.centerIn: parent; visible: list.count === 0; text: "No files match yet."; color: Theme.dim; font.family: Theme.sans; font.pixelSize: 15 }
            }
        }

        Card {
            Layout.preferredWidth: 400; Layout.fillHeight: true
            ColumnLayout {
                width: parent.width; height: 520; spacing: 12
                Text { text: page.selected.name !== undefined ? page.selected.name : "Select a file"; color: Theme.text
                       font.family: Theme.sans; font.pixelSize: 16; font.weight: Font.Bold; elide: Text.ElideMiddle; Layout.fillWidth: true }
                RowLayout {
                    visible: page.selected.path !== undefined; spacing: 8
                    AppButton { text: "Open"; implicitHeight: 34; onClicked: backend.openPath(page.selected.path) }
                    AppButton { text: "Show in folder"; kind: "secondary"; implicitHeight: 34; onClicked: backend.revealPath(page.selected.path) }
                }
                Rectangle {
                    Layout.fillWidth: true; Layout.fillHeight: true; radius: 10; color: Theme.consoleBg; border.width: 1; border.color: Theme.border; clip: true
                    Image {
                        visible: page.preview.kind === "image"
                        anchors.fill: parent; anchors.margins: 8; fillMode: Image.PreserveAspectFit; asynchronous: true
                        source: page.preview.kind === "image" ? page.preview.url : ""
                    }
                    Flickable {
                        visible: page.preview.kind === "text"
                        anchors.fill: parent; anchors.margins: 10; clip: true; contentHeight: pt.height; contentWidth: width
                        ScrollBar.vertical: ScrollBar { }
                        Text { id: pt; width: parent.width; wrapMode: Text.WrapAnywhere; color: "#C9D2EE"; font.family: Theme.mono; font.pixelSize: 12
                               text: page.preview.kind === "text" ? page.preview.text : "" }
                    }
                    Text {
                        visible: page.preview.kind === "binary" || page.preview.kind === "none"
                        anchors.centerIn: parent; width: parent.width - 40; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                        text: page.preview.kind === "binary" ? page.preview.text : "Click a file to preview it here.\nDouble-click to open it."
                        color: Theme.dim; font.family: Theme.sans; font.pixelSize: 14
                    }
                }
            }
        }
    }
}
