import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    property string market: ""
    property string workbookName: ""
    property string scope: "all orders in the workbook"
    signal confirmed()
    parent: Overlay.overlay
    anchors.centerIn: parent
    modal: true; dim: true
    width: Math.min(560, (parent ? parent.width : 700) - 80)
    padding: 0
    closePolicy: Popup.CloseOnEscape
    Overlay.modal: Rectangle { color: "#D0040612" }
    onOpened: typed.text = ""
    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 180 }
            NumberAnimation { property: "scale"; from: 0.95; to: 1; duration: 220; easing.type: Easing.OutBack }
        }
    }
    background: Rectangle { radius: 18; color: Theme.surface; border.width: 1; border.color: Theme.danger }

    contentItem: ColumnLayout {
        spacing: 14
        ColumnLayout {
            Layout.margins: 26; spacing: 12
            Text { text: "Place real orders?"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 24; font.weight: Font.Bold }
            Text {
                Layout.fillWidth: true; wrapMode: Text.WordWrap
                text: "This will submit " + root.scope + " from  " + root.workbookName
                      + "  to the T-Mobile dealer portal for " + root.market + ". Placed orders cannot be undone from this app."
                color: Theme.muted; font.family: Theme.sans; font.pixelSize: 14
            }
            Text { text: "Type  " + root.market + "  to confirm"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 14; font.weight: Font.DemiBold }
            Field { id: typed; Layout.fillWidth: true; mono: true; placeholder: root.market
                    onAccepted: if (typed.text.trim().toUpperCase() === root.market) { root.close(); root.confirmed() } }
            RowLayout {
                Layout.fillWidth: true; Layout.topMargin: 6; spacing: 10
                Item { Layout.fillWidth: true }
                AppButton { text: "Cancel"; kind: "secondary"; onClicked: root.close() }
                AppButton {
                    text: "Place orders now"; kind: "danger"; glyph: "➤"
                    enabledState: typed.text.trim().toUpperCase() === root.market
                    onClicked: { root.close(); root.confirmed() }
                }
            }
        }
    }
}
