import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

PageBase {
    id: page
    title: "Settings"
    subtitle: "Where files live, which login file to use, and your master data."
    signal navigate(int index)

    property string masterTarget: "devices"

    FileDialog {
        id: loginPicker; title: "Choose marketlogins.xlsx"; nameFilters: ["Excel workbooks (*.xlsx *.xlsm)"]
        onAccepted: backend.setCredentials(selectedFile.toString())
    }
    FileDialog {
        id: masterPicker; title: "Choose the new master workbook"; nameFilters: ["Excel workbooks (*.xlsx)"]
        onAccepted: backend.replaceMaster(page.masterTarget, selectedFile.toString())
    }
    FolderDialog { id: folderPicker; title: "Choose the workspace folder"; onAccepted: backend.setWorkspace(selectedFolder.toString()) }

    component Row2: RowLayout { spacing: 12; Layout.fillWidth: true }

    Card {
        Layout.fillWidth: true
        ColumnLayout {
            width: parent.width; spacing: 12
            Text { text: "Workspace folder"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 17; font.weight: Font.Bold }
            Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13
                   text: "All converted files, results, confirmations and logs are saved here — never inside the program folder — so sharing or updating the app can't fill anything up." }
            Row2 {
                Field { Layout.fillWidth: true; text: backend.workspacePath; mono: true; enabled: false }
                AppButton { text: "Open"; kind: "secondary"; onClicked: backend.openWorkspace() }
                AppButton { text: "Change…"; kind: "secondary"; enabledState: !backend.busy; onClicked: folderPicker.open() }
            }
        }
    }

    Card {
        Layout.fillWidth: true
        border.color: backend.credentialsOk ? Theme.border : Theme.warn
        ColumnLayout {
            width: parent.width; spacing: 12
            RowLayout {
                Text { text: "Login file"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 17; font.weight: Font.Bold; Layout.fillWidth: true }
                StatusPill { status: backend.credentialsOk ? "ready" : "warning"; label: backend.credentialsOk ? "Found" : "Not set" }
            }
            Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13
                   text: "Point to your marketlogins.xlsx. The app only remembers where it is — the file is never copied into the workspace or the project." }
            Row2 {
                Field { Layout.fillWidth: true; text: backend.credentialsPath; mono: true; enabled: false; placeholder: "No file chosen" }
                AppButton { text: "Browse…"; onClicked: loginPicker.open() }
            }
        }
    }

    Card {
        Layout.fillWidth: true
        ColumnLayout {
            width: parent.width; spacing: 12
            Text { text: "Browser for the dealer portal"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 17; font.weight: Font.Bold }
            Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13
                   text: "Automatic tries the built-in Chromium first, then Microsoft Edge, then Google Chrome — Edge comes with Windows, so nothing extra has to be installed." }
            Flow {
                Layout.fillWidth: true; spacing: 8
                Repeater {
                    model: [{ k: "auto", t: "Automatic" }, { k: "msedge", t: "Microsoft Edge" }, { k: "chrome", t: "Google Chrome" }, { k: "chromium", t: "Built-in Chromium" }]
                    delegate: Chip { required property var modelData; text: modelData.t; selected: backend.browser === modelData.k; onClicked: backend.setBrowser(modelData.k) }
                }
            }
        }
    }

    Card {
        Layout.fillWidth: true
        ColumnLayout {
            width: parent.width; spacing: 12
            Text { text: "Master data"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 17; font.weight: Font.Bold }
            Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13
                   text: "Devices (SKUs and pack sizes) and store details (addresses, reference names). Replacing a file keeps the previous version in masters/previous." }
            Row2 {
                Text { text: "Devices.xlsx"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 14; Layout.preferredWidth: 150 }
                AppButton { text: "Open"; kind: "secondary"; onClicked: backend.openMaster("devices") }
                AppButton { text: "Replace…"; kind: "secondary"; onClicked: { page.masterTarget = "devices"; masterPicker.open() } }
            }
            Row2 {
                Text { text: "MarketDetails.xlsx"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 14; Layout.preferredWidth: 150 }
                AppButton { text: "Open"; kind: "secondary"; onClicked: backend.openMaster("details") }
                AppButton { text: "Replace…"; kind: "secondary"; onClicked: { page.masterTarget = "details"; masterPicker.open() } }
            }
        }
    }

    Card {
        Layout.fillWidth: true
        ColumnLayout {
            width: parent.width; spacing: 12
            Text { text: "Housekeeping"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 17; font.weight: Font.Bold }
            Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 13
                   text: "Debug dumps (page snapshots saved when the portal misbehaves) can pile up. Order confirmations, results and logs are never deleted." }
            Row2 {
                Text { text: "Remove debug files older than"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 14 }
                Field { Layout.preferredWidth: 80; text: backend.debugKeepDays; mono: true; inputMethodHints: Qt.ImhDigitsOnly
                        onAccepted: backend.setDebugKeepDays(parseInt(text) || 30) }
                Text { text: "days"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: 14 }
                Item { Layout.fillWidth: true }
                AppButton { text: "Clean up now"; kind: "secondary"; onClicked: backend.purgeDebug() }
            }
        }
    }

    Text { text: backend.appName + "  ·  version " + backend.version; color: Theme.dim; font.family: Theme.sans; font.pixelSize: 12 }
}
