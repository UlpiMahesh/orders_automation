import QtQuick

Rectangle {
    id: root
    property real value: -1          // 0..1 determinate, <0 indeterminate
    property bool active: false
    implicitHeight: 5
    color: Theme.field
    clip: true

    Rectangle {
        visible: root.value >= 0
        height: parent.height
        width: parent.width * Math.min(1, root.value)
        Behavior on width { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Theme.accent }
            GradientStop { position: 1; color: Theme.accent2 }
        }
    }
    Rectangle {
        id: shimmer
        visible: root.active && root.value < 0
        width: parent.width * 0.32
        height: parent.height
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: "transparent" }
            GradientStop { position: 0.5; color: Theme.accent2 }
            GradientStop { position: 1; color: "transparent" }
        }
        NumberAnimation on x {
            running: shimmer.visible; loops: Animation.Infinite
            from: -shimmer.width; to: root.width; duration: 1300; easing.type: Easing.InOutSine
        }
    }
}
