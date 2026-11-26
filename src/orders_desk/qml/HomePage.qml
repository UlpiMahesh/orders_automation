import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

PageBase {
    id: page
    title: backend.appName
    subtitle: "Convert, check and place dealer orders — one click per step."
    signal navigate(int index)

    property var recent: backend.listRuns("").slice(0, 6)
    Connections { target: backend; function onRunsChanged() { page.recent = backend.listRuns("").slice(0, 6) } }

    // missing login banner
    Card {
        Layout.fillWidth: true
        visible: !backend.credentialsOk
        border.color: Theme.warn
        RowLayout {
            width: parent.width; spacing: 16
            Text { text: "🔑"; font.pixelSize: 26 }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 2
                Text { text: "Set your login file to enable the portal"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 16; font.weight: Font.DemiBold }
                Text { text: "Converting and checking work without it. Verifying and placing orders need marketlogins.xlsx."
                       color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
            AppButton { text: "Open Settings"; kind: "warn"; onClicked: page.navigate(6) }
        }
    }

    SectionTitle { text: "What would you like to do?" }
    GridLayout {
        Layout.fillWidth: true
        columns: width > 980 ? 4 : 2
        columnSpacing: 16; rowSpacing: 16
        Repeater {
            model: [
                { glyph: "⇄", title: "Convert orders", desc: "Turn a market workbook into a standard order file.", tone: "#7C5CFF", target: 1 },
                { glyph: "✔", title: "Check orders", desc: "Review every order and warning before anything is placed.", tone: "#22D3EE", target: 2 },
                { glyph: "➤", title: "Place orders", desc: "Build the carts on the dealer portal and submit.", tone: "#F0527A", target: 3 },
                { glyph: "▤", title: "Files & results", desc: "Open converted files, results, confirmations and logs.", tone: "#34D399", target: 4 }
            ]
            delegate: Card {
                required property var modelData
                Layout.fillWidth: true; Layout.preferredHeight: 168
                hoverable: true
                onClicked: page.navigate(modelData.target)
                Column {
                    width: parent.width; spacing: 10
                    Rectangle {
                        width: 46; height: 46; radius: 13; color: Qt.rgba(Qt.color(modelData.tone).r, Qt.color(modelData.tone).g, Qt.color(modelData.tone).b, 0.16)
                        Text { anchors.centerIn: parent; text: modelData.glyph; color: modelData.tone; font.pixelSize: 24 }
                    }
                    Text { text: modelData.title; color: Theme.text; font.family: Theme.sans; font.pixelSize: 18; font.weight: Font.Bold }
                    Text { text: modelData.desc; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13; wrapMode: Text.WordWrap; width: parent.width }
                }
            }
        }
    }

    SectionTitle { text: "Markets" }
    Flow {
        Layout.fillWidth: true
        spacing: 14
        Repeater {
            model: backend.markets
            delegate: Card {
                required property var modelData
                width: 292; height: modelData.canConvert ? 150 : 110
                hoverable: modelData.canConvert
                opacity: modelData.canConvert ? 1 : 0.5
                onClicked: { backend.setMarket(modelData.id); page.navigate(1) }
                Column {
                    width: parent.width; spacing: 7
                    RowLayout {
                        width: parent.width
                        Text { text: modelData.id; color: Theme.text; font.family: Theme.sans; font.pixelSize: 19; font.weight: Font.Bold; Layout.fillWidth: true }
                        StatusPill {
                            status: !modelData.canConvert ? "idle" : (modelData.convertedName !== "" ? "ready" : "idle")
                            label: !modelData.canConvert ? "Not set up" : (modelData.convertedName !== "" ? "Converted" : "Waiting")
                        }
                    }
                    Text { width: parent.width; elide: Text.ElideMiddle
                           text: modelData.canConvert ? (modelData.sourceName !== "" ? "Source  ·  " + modelData.sourceName : "Source  ·  none yet") : modelData.description
                           color: Theme.muted; font.family: Theme.sans; font.pixelSize: 12; maximumLineCount: 2; wrapMode: modelData.canConvert ? Text.NoWrap : Text.WordWrap }
                    Text { visible: modelData.canConvert; width: parent.width; elide: Text.ElideRight
                           text: modelData.convertedName !== "" ? "Converted  ·  " + modelData.orders + " orders, " + modelData.devices + " devices  ·  " + modelData.convertedWhen : "Converted  ·  nothing yet"
                           color: Theme.muted; font.family: Theme.sans; font.pixelSize: 12 }
                    Text { visible: modelData.canConvert; width: parent.width; elide: Text.ElideRight
                           text: modelData.lastPlaceWhen !== "" ? "Last run  ·  " + modelData.lastPlaceSummary + "  ·  " + modelData.lastPlaceWhen : "Last run  ·  none"
                           color: Theme.dim; font.family: Theme.sans; font.pixelSize: 12 }
                }
            }
        }
    }

    SectionTitle { text: "Recent activity" }
    Card {
        Layout.fillWidth: true
        padding: 8
        Column {
            width: parent.width
            Repeater {
                model: page.recent
                delegate: Item {
                    required property var modelData
                    width: parent.width; height: 46
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 14
                        StatusPill { status: modelData.status; Layout.preferredWidth: 96 }
                        Text { text: modelData.actionLabel + "  ·  " + modelData.market; color: Theme.text; font.family: Theme.sans; font.pixelSize: 14; font.weight: Font.DemiBold; Layout.preferredWidth: 220 }
                        Text { text: modelData.summary; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13; elide: Text.ElideRight; Layout.fillWidth: true }
                        Text { text: modelData.when; color: Theme.dim; font.family: Theme.sans; font.pixelSize: 12 }
                    }
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border; opacity: 0.6 }
                }
            }
            Text { visible: page.recent.length === 0; width: parent.width; height: 56; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter
                   text: "Nothing has run yet. Start with Convert orders."; color: Theme.dim; font.family: Theme.sans; font.pixelSize: 14 }
        }
    }
}
