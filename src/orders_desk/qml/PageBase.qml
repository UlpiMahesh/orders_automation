import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Scrolling page with a title block, a fade/slide-in when it becomes visible, and a column for content.
Item {
    id: root
    property string title: ""
    property string subtitle: ""
    property bool scrollable: true
    default property alias content: column.data

    opacity: 1
    onVisibleChanged: if (visible) { opacity = 0; enter.restart() }
    ParallelAnimation {
        id: enter
        NumberAnimation { target: root; property: "opacity"; to: 1; duration: 320; easing.type: Easing.OutCubic }
        NumberAnimation { target: shift; property: "y"; from: 14; to: 0; duration: 320; easing.type: Easing.OutCubic }
    }
    transform: Translate { id: shift }

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight + 72
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: root.scrollable
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: column
            x: 40; y: 34
            width: flick.width - 80
            spacing: 22

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Text {
                    text: root.title
                    color: Theme.text
                    font.family: Theme.sans; font.pixelSize: 30; font.weight: Font.Bold
                }
                Text {
                    visible: root.subtitle !== ""
                    text: root.subtitle
                    color: Theme.muted
                    font.family: Theme.sans; font.pixelSize: 15
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }
        }
    }
}
