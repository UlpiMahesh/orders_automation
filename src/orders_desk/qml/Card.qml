import QtQuick

Rectangle {
    id: root
    property bool hoverable: false
    property int padding: 20
    property bool hovered: false
    default property alias content: inner.data
    signal clicked()

    color: Theme.surface
    radius: Theme.radius
    border.width: 1
    border.color: hovered && hoverable ? Theme.accent : Theme.border
    implicitHeight: inner.childrenRect.height + padding * 2
    Behavior on border.color { ColorAnimation { duration: Theme.fast } }

    Rectangle {      // soft glow on hover
        anchors.fill: parent; radius: parent.radius
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0.49, 0.36, 1, 0.14) }
            GradientStop { position: 1.0; color: "transparent" }
        }
        opacity: root.hovered && root.hoverable ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.medium } }
    }
    Item {
        id: inner
        x: root.padding; y: root.padding
        width: root.width - root.padding * 2
        height: childrenRect.height
    }
    MouseArea {
        anchors.fill: parent
        hoverEnabled: root.hoverable
        enabled: root.hoverable
        cursorShape: root.hoverable ? Qt.PointingHandCursor : Qt.ArrowCursor
        onEntered: root.hovered = true
        onExited: root.hovered = false
        onClicked: root.clicked()
    }
}
