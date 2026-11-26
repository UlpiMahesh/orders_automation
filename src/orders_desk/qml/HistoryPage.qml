import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

PageBase {
    id: page
    title: "History"
    subtitle: "Every conversion, check and placement is recorded with its own folder, log and results."
    signal navigate(int index)

    property string marketFilter: ""
    property var runs: []
    property var selected: ({})
    property string logText: ""

    function reload() { runs = backend.listRuns(marketFilter) }
    function select(r) { selected = r; logText = backend.readRunLog(r.market, r.runId) }
    Component.onCompleted: reload()
    onMarketFilterChanged: reload()
    Connections { target: backend; function onRunsChanged() { page.reload() } }

    Flow {
        Layout.fillWidth: true; spacing: 8
        Chip { text: "All markets"; selected: page.marketFilter === ""; onClicked: page.marketFilter = "" }
        Repeater {
            model: backend.markets.filter(function (m) { return m.canConvert })
            delegate: Chip { required property var modelData; text: modelData.id; selected: page.marketFilter === modelData.id; onClicked: page.marketFilter = modelData.id }
        }
    }

    RowLayout {
        Layout.fillWidth: true; Layout.preferredHeight: 600; spacing: 16
        Card {
            Layout.fillWidth: true; Layout.fillHeight: true; padding: 6
            ListView {
                id: list
                anchors.fill: parent; clip: true; model: page.runs
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { }
                delegate: Item {
                    id: row
                    required property var modelData
                    width: list.width; height: 62
                    Rectangle { anchors.fill: parent; anchors.margins: 2; radius: 10
                                color: page.selected.runId === modelData.runId ? Qt.rgba(0.49, 0.36, 1, 0.20) : (hover.containsMouse ? Theme.surfaceHi : "transparent") }
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14; spacing: 12
                        StatusPill { status: modelData.status; Layout.preferredWidth: 92 }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 1
                            Text { text: modelData.actionLabel + "  ·  " + modelData.market; color: Theme.text; font.family: Theme.sans; font.pixelSize: 14; font.weight: Font.DemiBold }
                            Text { text: modelData.summary !== "" ? modelData.summary : "—"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 12; elide: Text.ElideRight; Layout.fillWidth: true }
                        }
                        ColumnLayout {
                            spacing: 1
                            Text { text: modelData.when; color: Theme.dim; font.family: Theme.sans; font.pixelSize: 12; Layout.alignment: Qt.AlignRight }
                            Text { text: modelData.duration; color: Theme.dim; font.family: Theme.sans; font.pixelSize: 11; Layout.alignment: Qt.AlignRight }
                        }
                    }
                    MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.select(modelData) }
                }
                Text { anchors.centerIn: parent; visible: list.count === 0; text: "No runs yet."; color: Theme.dim; font.family: Theme.sans; font.pixelSize: 15 }
            }
        }
        Card {
            Layout.preferredWidth: 460; Layout.fillHeight: true
            ColumnLayout {
                width: parent.width; height: 560; spacing: 12
                Text { text: page.selected.runId !== undefined ? page.selected.actionLabel + " · " + page.selected.market : "Select a run"
                       color: Theme.text; font.family: Theme.sans; font.pixelSize: 16; font.weight: Font.Bold }
                RowLayout {
                    visible: page.selected.runId !== undefined; spacing: 8
                    AppButton { text: "Open run folder"; kind: "secondary"; implicitHeight: 34; onClicked: backend.revealPath(page.selected.dir) }
                }
                Rectangle {
                    Layout.fillWidth: true; Layout.fillHeight: true; radius: 10; color: Theme.consoleBg; border.width: 1; border.color: Theme.border; clip: true
                    Flickable {
                        anchors.fill: parent; anchors.margins: 10; clip: true; contentHeight: lt.height; contentWidth: width
                        ScrollBar.vertical: ScrollBar { }
                        Text { id: lt; width: parent.width; wrapMode: Text.WrapAnywhere; color: "#C9D2EE"; font.family: Theme.mono; font.pixelSize: 12
                               text: page.selected.runId !== undefined ? page.logText : "The log of the selected run appears here." }
                    }
                }
            }
        }
    }
}
