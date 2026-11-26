import QtQuick

Rectangle {
    id: root
    property string status: ""
    property string label: status
    implicitHeight: 24
    implicitWidth: dotRow.implicitWidth + 20
    radius: 12
    color: Qt.rgba(Theme.statusColor(status).r, Theme.statusColor(status).g, Theme.statusColor(status).b, 0.14)
    Row {
        id: dotRow
        anchors.centerIn: parent; spacing: 7
        Rectangle { width: 7; height: 7; radius: 3.5; color: Theme.statusColor(root.status); anchors.verticalCenter: parent.verticalCenter
            SequentialAnimation on opacity {
                running: root.status === "running"; loops: Animation.Infinite
                NumberAnimation { to: 0.25; duration: 650 } NumberAnimation { to: 1; duration: 650 }
            }
        }
        Text { text: root.label; color: Theme.statusColor(root.status); font.family: Theme.sans; font.pixelSize: 12; font.weight: Font.DemiBold
               anchors.verticalCenter: parent.verticalCenter }
    }
}
