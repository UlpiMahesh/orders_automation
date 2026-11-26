pragma Singleton
import QtQuick

QtObject {
    // surfaces
    readonly property color bg: "#080C18"
    readonly property color sidebar: "#0B1020"
    readonly property color surface: "#121931"
    readonly property color surfaceHi: "#19234A"
    readonly property color field: "#0D1328"
    readonly property color border: "#222C4D"
    readonly property color borderHi: "#3A4880"
    // text
    readonly property color text: "#EDF0FB"
    readonly property color muted: "#97A3C6"
    readonly property color dim: "#5E6B90"
    // brand + status
    readonly property color accent: "#7C5CFF"
    readonly property color accent2: "#22D3EE"
    readonly property color ok: "#34D399"
    readonly property color warn: "#FBBF24"
    readonly property color danger: "#F87171"
    readonly property color consoleBg: "#060914"
    // type
    readonly property string sans: "Segoe UI"
    readonly property string mono: "Consolas"
    readonly property int radius: 14
    readonly property int fast: 140
    readonly property int medium: 260

    function statusColor(s) {
        if (s === "success" || s === "ready") return ok
        if (s === "failed" || s === "error") return danger
        if (s === "stopped" || s === "interrupted" || s === "warning") return warn
        if (s === "running") return accent2
        return dim
    }
    function levelColor(l) {
        if (l === "error" || l === "critical") return danger
        if (l === "warning") return warn
        if (l === "success") return ok
        if (l === "head") return accent2
        if (l === "you") return accent
        if (l === "muted" || l === "debug") return dim
        return "#C9D2EE"
    }
}
