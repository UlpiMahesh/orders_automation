import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property string title: "Live activity"
    implicitHeight: 360
    color: Theme.consoleBg
    radius: Theme.radius
    border.width: 1
    border.color: backend.busy ? Qt.rgba(0.13, 0.83, 0.93, 0.55) : Theme.border
    Behavior on border.color { ColorAnimation { duration: Theme.medium } }
    clip: true

    TextEdit { id: clip; visible: false }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true; Layout.preferredHeight: 46
            color: "transparent"
            RowLayout {
                anchors.fill: parent; anchors.leftMargin: 18; anchors.rightMargin: 12; spacing: 12
                StatusPill {
                    status: backend.busy ? "running" : "idle"
                    label: backend.busy ? (backend.taskLabel || "Working") : "Idle"
                }
                Text {
                    text: backend.progressText
                    visible: text !== ""
                    color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: root.title
                    color: Theme.dim; font.family: Theme.sans; font.pixelSize: 12; font.letterSpacing: 1.2
                }
                AppButton {
                    visible: backend.busy; text: "Stop"; kind: "danger"; glyph: "■"; implicitHeight: 30
                    onClicked: backend.stopTask()
                }
                AppButton {
                    text: "Copy"; kind: "ghost"; implicitHeight: 30
                    onClicked: { clip.text = backend.logModel.asText(); clip.selectAll(); clip.copy(); }
                }
                AppButton {
                    text: "Clear"; kind: "ghost"; implicitHeight: 30; enabledState: !backend.busy
                    onClicked: backend.logModel.clear()
                }
            }
        }
        ProgressStrip { Layout.fillWidth: true; active: backend.busy; value: backend.busy ? backend.progress : 0 }

        ListView {
            id: list
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.margins: 14
            clip: true
            model: backend.logModel
            property bool follow: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { }
            onCountChanged: if (follow) Qt.callLater(positionViewAtEnd)
            onMovementEnded: follow = atYEnd
            delegate: Row {
                required property string text
                required property string level
                required property string time
                width: list.width - 12
                spacing: 12
                Text {
                    text: time; width: 62
                    color: Theme.dim; font.family: Theme.mono; font.pixelSize: 12
                }
                Text {
                    width: parent.width - 74
                    text: parent.text
                    wrapMode: Text.WrapAnywhere
                    color: Theme.levelColor(parent.level)
                    font.family: Theme.mono; font.pixelSize: 13
                    font.bold: parent.level === "head"
                }
            }
            Text {
                anchors.centerIn: parent
                visible: list.count === 0
                text: "Output will appear here while a task runs."
                color: Theme.dim; font.family: Theme.sans; font.pixelSize: 14
            }
        }
    }
}
