import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    property alias text: input.text
    property alias placeholder: ph.text
    property bool mono: false
    property alias inputMethodHints: input.inputMethodHints
    signal accepted()
    implicitHeight: 42
    implicitWidth: 220
    radius: 10
    color: Theme.field
    border.width: input.activeFocus ? 2 : 1
    border.color: input.activeFocus ? Theme.accent : Theme.border
    Behavior on border.color { ColorAnimation { duration: Theme.fast } }

    TextInput {
        id: input
        anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14
        verticalAlignment: TextInput.AlignVCenter
        color: Theme.text; selectionColor: Theme.accent
        font.family: root.mono ? Theme.mono : Theme.sans; font.pixelSize: 14
        clip: true
        onAccepted: root.accepted()
        Text { id: ph; visible: input.text.length === 0 && !input.activeFocus; color: Theme.dim
               font: input.font; anchors.verticalCenter: parent.verticalCenter }
    }
}
