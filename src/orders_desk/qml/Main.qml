import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: win
    width: 1320; height: 840
    minimumWidth: 1080; minimumHeight: 700
    visible: true
    title: backend.appName
    color: Theme.bg

    property int pageIndex: 0
    function go(i) { pageIndex = i }

    onClosing: function (close) {
        if (backend.busy) { close.accepted = false; quitDialog.open() }
    }

    RowLayout {
        anchors.fill: parent; spacing: 0

        // ---------------- sidebar
        Rectangle {
            Layout.preferredWidth: 236; Layout.fillHeight: true
            color: Theme.sidebar
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }
            ColumnLayout {
                anchors.fill: parent; spacing: 4
                Item { Layout.preferredHeight: 26 }
                RowLayout {
                    Layout.leftMargin: 26; spacing: 12
                    Rectangle {
                        width: 38; height: 38; radius: 11
                        gradient: Gradient { orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: Theme.accent } GradientStop { position: 1; color: Theme.accent2 } }
                        Text { anchors.centerIn: parent; text: "◆"; color: "white"; font.pixelSize: 18 }
                    }
                    Column {
                        Text { text: backend.appName; color: Theme.text; font.family: Theme.sans; font.pixelSize: 17; font.weight: Font.Bold }
                        Text { text: "v" + backend.version; color: Theme.dim; font.family: Theme.sans; font.pixelSize: 11 }
                    }
                }
                Item { Layout.preferredHeight: 22 }
                Repeater {
                    model: [
                        { g: "⌂", t: "Home" }, { g: "⇄", t: "Convert" }, { g: "✔", t: "Check" }, { g: "➤", t: "Place" },
                        { g: "▤", t: "Files" }, { g: "◷", t: "History" }
                    ]
                    delegate: NavItem {
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        glyph: modelData.g; text: modelData.t; active: win.pageIndex === index
                        onClicked: win.go(index)
                    }
                }
                Item { Layout.fillHeight: true }
                NavItem { Layout.fillWidth: true; glyph: "⚙"; text: "Settings"; active: win.pageIndex === 6; onClicked: win.go(6) }
                Rectangle {
                    Layout.fillWidth: true; Layout.margins: 16; Layout.preferredHeight: 62; radius: 12
                    color: Theme.field; border.width: 1; border.color: backend.busy ? Theme.accent2 : Theme.border
                    Column {
                        anchors.centerIn: parent; spacing: 4
                        StatusPill { anchors.horizontalCenter: parent.horizontalCenter
                                     status: backend.busy ? "running" : "ready"; label: backend.busy ? backend.taskLabel : "Ready" }
                        Text { anchors.horizontalCenter: parent.horizontalCenter; visible: backend.busy
                               text: backend.taskMarket + (backend.progressText !== "" ? "  ·  " + backend.progressText : "")
                               color: Theme.muted; font.family: Theme.sans; font.pixelSize: 11 }
                    }
                    MouseArea { anchors.fill: parent; enabled: backend.busy; cursorShape: Qt.PointingHandCursor
                                onClicked: win.go(backend.taskAction === "convert" ? 1 : backend.taskAction === "check" ? 2 : 3) }
                }
                Item { Layout.preferredHeight: 6 }
            }
        }

        // ---------------- pages
        Item {
            Layout.fillWidth: true; Layout.fillHeight: true
            Rectangle {      // subtle top glow
                anchors.top: parent.top; width: parent.width; height: 220
                gradient: Gradient { GradientStop { position: 0; color: Qt.rgba(0.49, 0.36, 1, 0.10) } GradientStop { position: 1; color: "transparent" } }
            }
            StackLayout {
                anchors.fill: parent
                currentIndex: win.pageIndex
                HomePage { onNavigate: function (i) { win.go(i) } }
                ConvertPage { onNavigate: function (i) { win.go(i) } }
                CheckPage { onNavigate: function (i) { win.go(i) } }
                PlacePage { onNavigate: function (i) { win.go(i) } }
                FilesPage { }
                HistoryPage { }
                SettingsPage { }
            }
        }
    }

    PromptDialog { id: prompt }
    Toast { anchors.right: parent.right; anchors.bottom: parent.bottom; z: 50 }

    Popup {
        id: quitDialog
        parent: Overlay.overlay; anchors.centerIn: parent; modal: true; dim: true; padding: 24
        width: 480
        Overlay.modal: Rectangle { color: "#D0040612" }
        background: Rectangle { radius: 16; color: Theme.surface; border.width: 1; border.color: Theme.warn }
        contentItem: ColumnLayout {
            spacing: 14
            Text { text: "A task is still running"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 20; font.weight: Font.Bold }
            Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 14
                   text: "Closing now stops it and shuts the browser. An order in progress may stay open in the portal cart." }
            RowLayout {
                Item { Layout.fillWidth: true }
                AppButton { text: "Keep working"; kind: "secondary"; onClicked: quitDialog.close() }
                AppButton { text: "Stop and close"; kind: "danger"; onClicked: { backend.shutdown(); Qt.quit() } }
            }
        }
    }
}
