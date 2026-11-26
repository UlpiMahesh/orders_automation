import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    readonly property var prompt: backend.pendingPrompt
    readonly property bool active: !!(prompt && prompt.id)
    readonly property bool placesOrder: active && prompt.live && prompt.options && prompt.options.length > 0
                                        && /PLACE/.test(prompt.options[0].label || "")
    parent: Overlay.overlay
    anchors.centerIn: parent
    modal: true
    dim: true
    closePolicy: Popup.NoAutoClose
    width: Math.min(760, (parent ? parent.width : 800) - 80)
    padding: 0
    visible: active

    Overlay.modal: Rectangle { color: "#D0040612" }
    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 200 }
            NumberAnimation { property: "scale"; from: 0.94; to: 1; duration: 240; easing.type: Easing.OutBack }
        }
    }
    exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: 120 } }

    background: Rectangle {
        radius: 18; color: Theme.surface
        border.width: 1; border.color: root.placesOrder ? Theme.danger : Theme.accent
    }

    contentItem: ColumnLayout {
        spacing: 14
        // header
        ColumnLayout {
            Layout.margins: 24; Layout.bottomMargin: 0; spacing: 6
            Text {
                text: root.active ? root.prompt.title : ""
                color: Theme.text; font.family: Theme.sans; font.pixelSize: 22; font.weight: Font.Bold
            }
            Text {
                text: backend.taskMarket + "  ·  the automation is paused and waiting for you"
                color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13
            }
        }
        Rectangle {
            visible: root.placesOrder
            Layout.fillWidth: true; Layout.leftMargin: 24; Layout.rightMargin: 24
            implicitHeight: warnText.implicitHeight + 18; radius: 10
            color: Qt.rgba(0.97, 0.44, 0.44, 0.14); border.width: 1; border.color: Theme.danger
            Text {
                id: warnText
                anchors.fill: parent; anchors.margins: 9; wrapMode: Text.WordWrap
                text: "LIVE RUN — the first button places a real order on the dealer portal if the final page matches the sheet."
                color: Theme.danger; font.family: Theme.sans; font.pixelSize: 13; font.weight: Font.DemiBold
            }
        }
        // context
        Rectangle {
            Layout.fillWidth: true; Layout.leftMargin: 24; Layout.rightMargin: 24
            Layout.preferredHeight: Math.min(230, ctx.contentHeight + 24)
            visible: root.active && root.prompt.body && root.prompt.body.length > 0
            radius: 10; color: Theme.consoleBg; border.width: 1; border.color: Theme.border
            Flickable {
                anchors.fill: parent; anchors.margins: 12; clip: true
                contentHeight: ctx.contentHeight; boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { }
                Text {
                    id: ctx
                    width: parent.width
                    text: root.active && root.prompt.body ? root.prompt.body.join("\n") : ""
                    wrapMode: Text.WrapAnywhere
                    color: "#C9D2EE"; font.family: Theme.mono; font.pixelSize: 12
                }
            }
        }
        // options
        ColumnLayout {
            Layout.fillWidth: true; Layout.leftMargin: 24; Layout.rightMargin: 24; spacing: 9
            Repeater {
                model: root.active ? root.prompt.options : []
                delegate: AppButton {
                    required property var modelData
                    Layout.fillWidth: true
                    big: true
                    text: modelData.label
                    kind: (root.placesOrder && modelData.style === "primary") ? "danger"
                          : (root.placesOrder && modelData.style === "danger") ? "secondary"
                          : modelData.style === "danger" ? "danger" : modelData.style === "warn" ? "warn"
                          : modelData.style === "primary" ? "primary" : "secondary"
                    onClicked: backend.answerPrompt(modelData.key)
                }
            }
        }
        // custom reply
        RowLayout {
            Layout.fillWidth: true; Layout.leftMargin: 24; Layout.rightMargin: 24; Layout.bottomMargin: 22
            spacing: 10
            Field { id: custom; Layout.fillWidth: true; placeholder: "Or type a reply for the automation…"; mono: true
                    onAccepted: { backend.answerPrompt(custom.text); custom.text = "" } }
            AppButton { text: "Send"; kind: "secondary"; onClicked: { backend.answerPrompt(custom.text); custom.text = "" } }
        }
    }
}
