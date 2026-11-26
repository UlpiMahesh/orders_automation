import QtQuick

Item {
    id: root
    property string glyph: ""
    property string text: ""
    property bool active: false
    property string badge: ""
    signal clicked()
    height: 46

    Rectangle {
        anchors.fill: parent
        anchors.leftMargin: 10; anchors.rightMargin: 10
        radius: 11
        color: root.active ? Qt.rgba(0.49, 0.36, 1, 0.20) : (mouse.containsMouse ? Qt.rgba(1, 1, 1, 0.05) : "transparent")
        Behavior on color { ColorAnimation { duration: Theme.fast } }
    }
    Rectangle {      // active indicator
        width: 3; radius: 2
        height: root.active ? 24 : 0
        anchors.verticalCenter: parent.verticalCenter
        x: 0
        gradient: Gradient {
            GradientStop { position: 0; color: Theme.accent }
            GradientStop { position: 1; color: Theme.accent2 }
        }
        Behavior on height { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutCubic } }
    }
    Row {
        anchors.verticalCenter: parent.verticalCenter
        x: 28
        spacing: 14
        Text {
            text: root.glyph; width: 22; horizontalAlignment: Text.AlignHCenter
            color: root.active ? Theme.accent2 : Theme.muted
            font.pixelSize: 18; anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: root.text
            color: root.active ? "white" : (mouse.containsMouse ? Theme.text : Theme.muted)
            font.family: Theme.sans; font.pixelSize: 15; font.weight: root.active ? Font.DemiBold : Font.Normal
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    Rectangle {
        visible: root.badge !== ""
        anchors.right: parent.right; anchors.rightMargin: 24; anchors.verticalCenter: parent.verticalCenter
        width: badgeText.implicitWidth + 14; height: 20; radius: 10; color: Theme.accent2
        Text { id: badgeText; anchors.centerIn: parent; text: root.badge; color: "#04121A"; font.pixelSize: 11; font.weight: Font.Bold }
    }
    MouseArea {
        id: mouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
