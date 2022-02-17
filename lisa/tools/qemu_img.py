from lisa.executable import Tool

class QemuImg(Tool):
    @property
    def command(self) -> str:
        return "qemu-img"

    def createDiffQcow2(self, output_img_path, backing_img_path):
        params = f"create -F qcow2 -f qcow2 -b {backing_img_path} {output_img_path}"
        self.run(params, True)

