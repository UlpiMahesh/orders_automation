import QtQuick

Rectangle {
    id: root
    property string value: "0"
    property string caption: ""
    property color tone: Theme.text
    implicitWidth: 150; implicitHeight: 86
    radius: 12; color: Theme.field; border.width: 1; border.color: Theme.border
    Column {
        anchors.centerIn: parent; spacing: 2
        Text { text: root.value; color: root.tone; font.family: Theme.sans; font.pixelSize: 30; font.weight: Font.Bold
               anchors.horizontalCenter: parent.horizontalCenter }
        Text { text: root.caption; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 12
               anchors.horizontalCenter: parent.horizontalCenter }
    }
}
