import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

PageBase {
    id: page
    title: "Place orders"
    subtitle: "The automation opens the dealer portal, builds each cart from your workbook and asks you whenever it needs a decision."
    signal navigate(int index)

    property var workbooks: []
    property string workbookPath: ""
    readonly property string workbookName: {
        for (var i = 0; i < workbooks.length; i++) if (workbooks[i].path === workbookPath) return workbooks[i].name
        return ""
    }
    readonly property bool ready: !backend.busy && workbookPath !== "" && backend.credentialsOk

    function reload() { workbooks = backend.convertedList(backend.market); workbookPath = workbooks.length ? workbooks[0].path : "" }
    Component.onCompleted: reload()
    Connections {
        target: backend
        function onMarketChanged() { page.reload() }
        function onTaskFinished(r) { if (r.action === "convert" && r.status === "success") page.reload() }
    }

    Card {
        Layout.fillWidth: true
        visible: !backend.credentialsOk
        border.color: Theme.warn
        RowLayout {
            width: parent.width; spacing: 16
            Text { text: "🔑"; font.pixelSize: 24 }
            Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: "The login file (marketlogins.xlsx) is not set. Add it in Settings to enable the portal steps."
                   color: Theme.text; font.family: Theme.sans; font.pixelSize: 14 }
            AppButton { text: "Open Settings"; kind: "warn"; onClicked: page.navigate(6) }
        }
    }

    SectionTitle { text: "1  ·  Market" }
    MarketPicker { Layout.fillWidth: true; needs: "place" }

    SectionTitle { text: "2  ·  Converted workbook" }
    Flow {
        Layout.fillWidth: true; spacing: 8
        Repeater {
            model: page.workbooks.slice(0, 6)
            delegate: Chip {
                required property var modelData
                text: modelData.name; sub: modelData.modified
                selected: page.workbookPath === modelData.path
                onClicked: page.workbookPath = modelData.path
            }
        }
        Text { visible: page.workbooks.length === 0; text: "No converted workbook for " + backend.market + " yet."
               color: Theme.warn; font.family: Theme.sans; font.pixelSize: 14 }
    }

    SectionTitle { text: "3  ·  Optional filters" }
    RowLayout {
        spacing: 14
        ColumnLayout {
            spacing: 5
            Text { text: "Only the first … orders"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 12 }
            Field { id: limitField; Layout.preferredWidth: 170; placeholder: "all orders"; mono: true; inputMethodHints: Qt.ImhDigitsOnly }
        }
        ColumnLayout {
            Layout.fillWidth: true; spacing: 5
            Text { text: "Only these reference names (space separated)"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 12 }
            Field { id: refsField; Layout.fillWidth: true; placeholder: "e.g. 24NOV261300WACOG"; mono: true }
        }
    }

    SectionTitle { text: "4  ·  Run" }
    GridLayout {
        Layout.fillWidth: true; columns: width > 900 ? 2 : 1; columnSpacing: 16; rowSpacing: 16
        Card {
            Layout.fillWidth: true; Layout.preferredHeight: 178
            ColumnLayout {
                width: parent.width; spacing: 10
                Text { text: "Verify on the portal"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 18; font.weight: Font.Bold }
                Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13
                       text: "Goes all the way to the final order page and checks it against your workbook. The Order button is never clicked, and the cart is cancelled afterwards." }
                AppButton { text: "Verify orders"; glyph: "◎"; kind: "secondary"
                            busy: backend.busy && backend.taskAction === "verify"; enabledState: page.ready
                            onClicked: backend.placeOrders(backend.market, page.workbookPath, "verify", parseInt(limitField.text) || 0, refsField.text, "") }
            }
        }
        Card {
            Layout.fillWidth: true; Layout.preferredHeight: 178
            border.color: Qt.rgba(0.97, 0.44, 0.44, 0.5)
            ColumnLayout {
                width: parent.width; spacing: 10
                Text { text: "Place the orders"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 18; font.weight: Font.Bold }
                Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13
                       text: "Builds each order and clicks Order when the final page matches the sheet. You confirm by typing the market name first." }
                AppButton { text: "Place orders"; glyph: "➤"; kind: "danger"
                            busy: backend.busy && backend.taskAction === "live"; enabledState: page.ready
                            onClicked: { confirm.market = backend.market; confirm.workbookName = page.workbookName
                                         confirm.scope = (parseInt(limitField.text) > 0 ? "the first " + limitField.text + " order(s)" : (refsField.text.trim() !== "" ? "the selected order(s)" : "ALL orders"))
                                         confirm.open() } }
            }
        }
    }

    ConsolePanel {
        Layout.fillWidth: true; Layout.preferredHeight: 420
        title: "PORTAL ACTIVITY"
    }

    ConfirmLiveDialog {
        id: confirm
        onConfirmed: backend.placeOrders(backend.market, page.workbookPath, "live", parseInt(limitField.text) || 0, refsField.text, backend.market)
    }
}
