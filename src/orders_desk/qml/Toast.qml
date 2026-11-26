import QtQuick

Item {
    id: root
    property string message: ""
    property string level: "info"
    width: 420; height: box.height
    visible: opacity > 0
    opacity: 0
    anchors.rightMargin: 28; anchors.bottomMargin: 28

    function show(msg, lvl) {
        message = msg; level = lvl
        hide.restart(); appear.restart()
    }
    Connections { target: backend; function onToast(msg, lvl) { root.show(msg, lvl) } }

    ParallelAnimation {
        id: appear
        NumberAnimation { target: root; property: "opacity"; to: 1; duration: 200 }
        NumberAnimation { target: slide; property: "y"; from: 16; to: 0; duration: 260; easing.type: Easing.OutCubic }
    }
    Timer { id: hide; interval: 5200; onTriggered: fade.start() }
    NumberAnimation { id: fade; target: root; property: "opacity"; to: 0; duration: 300 }
    transform: Translate { id: slide }

    Rectangle {
        id: box
        width: parent.width; height: txt.implicitHeight + 30
        radius: 14; color: Theme.surfaceHi
        border.width: 1; border.color: root.level === "error" ? Theme.danger : root.level === "warning" ? Theme.warn
                                     : root.level === "success" ? Theme.ok : Theme.borderHi
        Rectangle { width: 4; height: parent.height - 20; radius: 2; x: 10; anchors.verticalCenter: parent.verticalCenter
                    color: parent.border.color }
        Text {
            id: txt
            x: 28; y: 15; width: parent.width - 44
            text: root.message; wrapMode: Text.WordWrap
            color: Theme.text; font.family: Theme.sans; font.pixelSize: 14
        }
        MouseArea { anchors.fill: parent; onClicked: fade.start() }
    }
}
