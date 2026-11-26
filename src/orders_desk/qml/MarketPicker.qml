import QtQuick
import QtQuick.Layouts

Flow {
    id: root
    property string needs: "convert"     // convert | place
    property bool lockWhileBusy: true
    spacing: 10
    Repeater {
        model: backend.markets
        delegate: Chip {
            required property var modelData
            readonly property bool capable: root.needs === "place" ? modelData.canPlace : modelData.canConvert
            text: modelData.id
            sub: capable ? "" : "soon"
            selected: backend.market === modelData.id
            disabledChip: !capable || (root.lockWhileBusy && backend.busy)
            onClicked: backend.setMarket(modelData.id)
        }
    }
}
