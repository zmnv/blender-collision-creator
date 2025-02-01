import bpy
import bmesh
import numpy as np
from mathutils import Matrix

bl_info = {
    "name": "Collision Creator",
    "description": "Create collision blocks and convex hulls based on selected area.",
    "author": "@zmnv",
    "version": (1, 0, 2),
    "blender": (3, 0, 0),
    "location": "View3D > Tool Shelf > Collision Creator",
    "category": "Object",
}

# Group for panel properties
class CollisionBlockProperties(bpy.types.PropertyGroup): 
    method: bpy.props.EnumProperty(
        name="Method",
        description="Method for creating the block",
        items=[
            ('convex', "Convex Hull", "Creating a block based on a convex hull"),
            ('box', "Box", "Simple block fully covers the selected area")
        ],
        default='convex'
    )

    use_selected_mesh_name: bpy.props.EnumProperty(
        name="Use selected mesh name",
        description="Choose between using the active object name or custom name",
        items=[
            ('true', "Active Mesh Name", "Use the active object name with a prefix"),
            ('false', "Custom", "Use a custom name for the block")
        ],
        default='true'
    )
    
    custom_name: bpy.props.StringProperty(
        name="Name",
        description="The name of the created block",
        default="CollisionBlock"
    )
    
    mesh_prefix: bpy.props.StringProperty(
        name="Prefix",
        description="Prefix used in the name of the created block",
        default="UCX_"
    )

    auto_focus: bpy.props.BoolProperty(
        name="Select created block automatically",
        description="Automatically select the created block after it's created",
        default=False
    )

    offset: bpy.props.FloatVectorProperty(
        name="Offset",
        description="Offset for the block along X, Y, Z axes",
        default=(0.0, 0.0, 0.0),
        subtype="XYZ"
    )

    rotation: bpy.props.FloatVectorProperty(
        name="Rotation",
        description="Rotation of the block along X, Y, Z axes in radians",
        default=(0.0, 0.0, 0.0),  # Default rotation is 0 for each axis
        subtype="EULER"
    )

def get_selected_vertices(obj):
    """Get selected vertices in Edit Mode or all vertices in Object Mode."""
    if bpy.context.mode == 'EDIT_MESH':
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        return [obj.matrix_world @ v.co for v in bm.verts if v.select]  # Global coordinates
    elif bpy.context.mode == 'OBJECT':
        return [obj.matrix_world @ v.co for v in obj.data.vertices]  # Global coordinates
    return []

def generate_block_name(obj_name, use_selected_mesh_name, prefix, custom_name, block_number):
    """Generate block name based on the chosen mode."""
    if use_selected_mesh_name == 'true':
        return f"{prefix}{obj_name}_{str(block_number).zfill(2)}"
    else:
        return custom_name

def refresh_object_names(prefix, active_object_name):
    """Refresh names of objects that start with the given prefix and include the active object name."""
    block_number = 1  # Start numbering from 1
    for obj in bpy.data.objects:
        if obj.name.startswith(prefix):
            new_name = f"{prefix}{active_object_name}_{str(block_number).zfill(2)}"
            obj.name = new_name
            block_number += 1
    print(f"Names refreshed for objects starting with {prefix}")

def create_material_if_needed():
    """Create material named 'CollisionBlockMaterial' if it doesn't exist, and return the material."""
    material_name = "CollisionBlockMaterial"
    
    material = bpy.data.materials.get(material_name)
    if material is None:
        material = bpy.data.materials.new(name=material_name)
        material.use_nodes = True
        material.node_tree.nodes.clear()
        bsdf = material.node_tree.nodes.new(type="ShaderNodeBsdfPrincipled")
        bsdf.inputs["Metallic"].default_value = 0
        bsdf.inputs["Roughness"].default_value = 1
        bsdf.inputs["Base Color"].default_value = (0.047, 1, 0, 1)  # Light green
        material_output = material.node_tree.nodes.new(type="ShaderNodeOutputMaterial")
        material.node_tree.links.new(bsdf.outputs["BSDF"], material_output.inputs["Surface"])
    return material

def apply_material(obj, material):
    """Apply material to the object."""
    if obj.data.materials:
        obj.data.materials[0] = material
    else:
        obj.data.materials.append(material)

def apply_scale_offset_rotation(block, offset, rotation):
    """Apply offset, and rotation to the created block."""
    block.location = (block.location[0] + offset[0], block.location[1] + offset[1], block.location[2] + offset[2])
    block.rotation_euler = rotation
    bpy.ops.object.transform_apply(location=True, rotation=True)

def move_origin_to_geometry_center(block):
    """Move the origin of the block to the geometric center."""
    # Активируем и выбираем нужный объект
    bpy.context.view_layer.objects.active = block
    block.select_set(True)

    # Переключаемся в Object Mode, если требуется
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Перемещаем origin в центр геометрии
    bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')

def create_convex_hull(selected_verts):
    """Create a convex hull around the selected vertices, removing isolated vertices."""
    bm = bmesh.new()
    
    # Add vertices from the selected verts
    for v in selected_verts:
        bm.verts.new(v)
    
    bm.verts.ensure_lookup_table()
    
    # Create convex hull
    bmesh.ops.convex_hull(bm, input=bm.verts)
    
    # Remove isolated vertices (those not part of any edge)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_edges], context='VERTS')
    
    # Create the mesh for the convex hull
    mesh = bpy.data.meshes.new("Convex_Hull")
    bm.to_mesh(mesh)
    bm.free()
    
    obj = bpy.data.objects.new("Convex_Hull", mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def compute_pca_orientation(vertices):
    """Compute the PCA to find the orientation of the selected vertices."""
    coords = np.array(vertices)
    coords_centered = coords - np.mean(coords, axis=0)
    cov_matrix = np.cov(coords_centered.T)
    eigenvalues, eigenvectors = np.linalg.eigh(cov_matrix)
    return eigenvectors

def create_collision_block(context, method, use_selected_mesh_name, prefix, custom_name, auto_focus, offset, rotation):
    current_mode = bpy.context.mode

    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        print("Please select a Mesh object")
        return
    
    selected_verts = get_selected_vertices(obj)
    if not selected_verts:
        print("No vertices selected!")
        return
    
    coords = np.array([[v.x, v.y, v.z] for v in selected_verts])
    min_x, min_y, min_z = np.min(coords, axis=0)
    max_x, max_y, max_z = np.max(coords, axis=0)
    
    block_number = len([obj for obj in bpy.data.objects if obj.name.startswith(custom_name if use_selected_mesh_name == 'false' else prefix)]) + 1
    block_name = generate_block_name(obj.name, use_selected_mesh_name, prefix, custom_name, block_number)
    
    previous_selection = [obj for obj in bpy.context.selected_objects] if not auto_focus else []
    active_obj = obj

    if method == 'convex':
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Compute PCA orientation for the selected vertices
        orientation = compute_pca_orientation(selected_verts)
        matrix_orientation = Matrix(orientation).to_4x4()

        # Create the convex hull
        new_block = create_convex_hull(selected_verts)

        # Apply orientation
        new_block.matrix_world = matrix_orientation

        # Set the name of the block
        new_block.name = block_name

    elif method == 'box':
        center = ((min_x + max_x) / 2, (min_y + max_y) / 2, (min_z + max_z) / 2)
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.mesh.primitive_cube_add(size=1, location=center)
        new_block = context.object
        mesh = new_block.data
        
        bm = bmesh.new()
        bm.from_mesh(mesh)
        for v in bm.verts:
            global_co = new_block.matrix_world @ v.co
            global_co.x = min_x if global_co.x < center[0] else max_x
            global_co.y = min_y if global_co.y < center[1] else max_y
            global_co.z = min_z if global_co.z < center[2] else max_z
            v.co = new_block.matrix_world.inverted() @ global_co
        bm.to_mesh(mesh)
        bm.free()

        new_block.name = block_name

    material = create_material_if_needed()
    apply_material(new_block, material)
    apply_scale_offset_rotation(new_block, offset, rotation)
    # Move origin to the geometric center
    move_origin_to_geometry_center(new_block)

    # If auto_focus is True, select the new block and deselect the original mesh
    if auto_focus:
        bpy.ops.object.select_all(action='DESELECT')
        new_block.select_set(True)
        bpy.context.view_layer.objects.active = new_block
    else:
        if not auto_focus:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in previous_selection:
                obj.select_set(True)
            context.view_layer.objects.active = active_obj

    if current_mode == 'EDIT_MESH':
        bpy.ops.object.mode_set(mode='EDIT')

# Operator for refreshing names
class OBJECT_OT_refresh_object_names(bpy.types.Operator):
    """Refresh names of objects starting with the given prefix"""
    bl_idname = "object.refresh_object_names"
    bl_label = "Refresh Names"

    def execute(self, context):
        props = context.scene.collision_block_props
        active_obj = context.view_layer.objects.active
        if active_obj is not None:
            refresh_object_names(props.mesh_prefix, active_obj.name)
        return {'FINISHED'}

# Operator for creating a collision block
class OBJECT_OT_create_collision_block(bpy.types.Operator):
    """Create a collision block based on the selected area"""
    bl_idname = "object.create_collision_block"
    bl_label = "Create Block"
    
    def execute(self, context):
        props = context.scene.collision_block_props
        create_collision_block(
            context,
            props.method,
            props.use_selected_mesh_name,
            props.mesh_prefix,
            props.custom_name,
            props.auto_focus,
            props.offset,
            props.rotation
        )
        return {'FINISHED'}

# Panel for the UI button
class VIEW3D_PT_collision_block_panel(bpy.types.Panel):
    bl_label = "Collision Creator"
    bl_idname = "VIEW3D_PT_collision_block_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Collision Creator'

    def draw(self, context):
        layout = self.layout
        props = context.scene.collision_block_props
        
        layout.prop(props, "use_selected_mesh_name", expand=True)
        if props.use_selected_mesh_name == 'true':
            layout.operator("object.refresh_object_names", text="Refresh Names")
            layout.prop(props, "mesh_prefix", text="Prefix")
        else:
            layout.prop(props, "custom_name", text="Name")
        
        layout.prop(props, "method", text="Method", expand=True)
        layout.prop(props, "offset", text="Offset")
        layout.prop(props, "rotation", text="Rotation")
        layout.prop(props, "auto_focus", text="Select created block automatically")
        layout.separator()
        layout.operator("object.create_collision_block")

# Register the plugin and properties
def register():
    bpy.utils.register_class(CollisionBlockProperties)
    bpy.utils.register_class(OBJECT_OT_create_collision_block)
    bpy.utils.register_class(OBJECT_OT_refresh_object_names)
    bpy.utils.register_class(VIEW3D_PT_collision_block_panel)
    bpy.types.Scene.collision_block_props = bpy.props.PointerProperty(type=CollisionBlockProperties)

# Unregister the plugin and properties
def unregister():
    bpy.utils.unregister_class(CollisionBlockProperties)
    bpy.utils.unregister_class(OBJECT_OT_create_collision_block)
    bpy.utils.unregister_class(OBJECT_OT_refresh_object_names)
    bpy.utils.unregister_class(VIEW3D_PT_collision_block_panel)
    del bpy.types.Scene.collision_block_props

if __name__ == "__main__":
    register()
