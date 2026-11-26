import QtQuick

Item {
    id: root
    property string text: ""
    property string sub: ""
    property bool selected: false
    property bool disabledChip: false
    signal clicked()

    implicitHeight: 38
    implicitWidth: label.implicitWidth + 32 + (subLabel.visible ? subLabel.implicitWidth + 8 : 0)
    opacity: disabledChip ? 0.4 : 1

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: root.selected ? Qt.rgba(0.49, 0.36, 1, 0.22) : (mouse.containsMouse ? Theme.surfaceHi : Theme.surface)
        border.width: 1
        border.color: root.selected ? Theme.accent : (mouse.containsMouse ? Theme.borderHi : Theme.border)
        Behavior on color { ColorAnimation { duration: Theme.fast } }
        Behavior on border.color { ColorAnimation { duration: Theme.fast } }
    }
    Row {
        anchors.centerIn: parent
        spacing: 8
        Text {
            id: label
            text: root.text
            color: root.selected ? "white" : Theme.text
            font.family: Theme.sans; font.pixelSize: 14; font.weight: Font.DemiBold
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            id: subLabel
            visible: root.sub !== ""
            text: root.sub
            color: Theme.dim
            font.family: Theme.sans; font.pixelSize: 11
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: root.disabledChip ? Qt.ForbiddenCursor : Qt.PointingHandCursor
        onClicked: if (!root.disabledChip) root.clicked()
    }
}
