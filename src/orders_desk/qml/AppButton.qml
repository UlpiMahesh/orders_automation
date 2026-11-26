import QtQuick

Item {
    id: root
    property string text: ""
    property string glyph: ""
    property string kind: "primary"      // primary | secondary | danger | warn | ghost
    property bool busy: false
    property bool big: false
    property bool enabledState: true
    signal clicked()

    implicitHeight: big ? 52 : 40
    implicitWidth: row.implicitWidth + (big ? 44 : 30)
    opacity: enabledState ? 1.0 : 0.38
    scale: mouse.pressed && enabledState ? 0.97 : 1.0
    Behavior on scale { NumberAnimation { duration: 90 } }
    activeFocusOnTab: true
    Keys.onReturnPressed: if (enabledState) root.clicked()
    Keys.onSpacePressed: if (enabledState) root.clicked()

    readonly property bool grad: kind === "primary" || kind === "danger"

    Rectangle {
        id: bg
        anchors.fill: parent
        radius: 11
        border.width: root.kind === "primary" || root.kind === "danger" ? 0 : 1
        border.color: mouse.containsMouse ? Theme.borderHi : Theme.border
        color: {
            if (root.kind === "secondary") return mouse.containsMouse ? Theme.surfaceHi : Theme.surface
            if (root.kind === "warn") return mouse.containsMouse ? "#3A2E10" : "#2A210C"
            if (root.kind === "ghost") return mouse.containsMouse ? Theme.surface : "transparent"
            return "transparent"
        }
        gradient: root.grad ? grad2 : null
        Behavior on color { ColorAnimation { duration: Theme.fast } }
    }
    Gradient {
        id: grad2
        orientation: Gradient.Horizontal
        GradientStop { position: 0.0; color: root.kind === "danger" ? "#F0527A" : Theme.accent }
        GradientStop { position: 1.0; color: root.kind === "danger" ? "#FF8A4C" : Theme.accent2 }
    }
    Rectangle {          // hover sheen
        anchors.fill: parent; radius: 11
        color: "white"; opacity: root.grad && mouse.containsMouse ? 0.12 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.fast } }
    }
    Rectangle {          // keyboard focus ring
        anchors.fill: parent; anchors.margins: -3; radius: 14; color: "transparent"
        border.width: root.activeFocus ? 2 : 0; border.color: Theme.accent2
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 9
        Text {
            visible: root.glyph !== "" && !root.busy
            text: root.glyph
            color: root.kind === "warn" ? Theme.warn : (root.grad ? "white" : Theme.text)
            font.pixelSize: root.big ? 19 : 16
            anchors.verticalCenter: parent.verticalCenter
        }
        Item {
            visible: root.busy
            width: 16; height: 16
            anchors.verticalCenter: parent.verticalCenter
            RotationAnimator on rotation { from: 0; to: 360; duration: 850; loops: Animation.Infinite; running: root.busy }
            Rectangle { anchors.fill: parent; radius: 8; color: "transparent"; border.width: 2; border.color: "white"; opacity: 0.3 }
            Rectangle { width: 5; height: 5; radius: 2.5; color: "white"; anchors.horizontalCenter: parent.horizontalCenter; y: -1 }
        }
        Text {
            text: root.text
            color: root.kind === "warn" ? Theme.warn : (root.grad ? "white" : Theme.text)
            font.family: Theme.sans
            font.pixelSize: root.big ? 16 : 14
            font.weight: Font.DemiBold
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        enabled: root.enabledState
        cursorShape: root.enabledState ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.clicked()
    }
}
