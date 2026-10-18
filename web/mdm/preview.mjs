// Read-only fixtures, imported only after an explicit simulation deployment config.
const fixtures=[
  {id:'11111111-1111-4111-8111-111111111111',name:'Synthetic Maya Chen',reference:'SYN-PREVIEW-MAYA',type:'PERSON',email:'maya.chen@example.invalid'},
  {id:'22222222-2222-4222-8222-222222222222',name:'Synthetic Aster Trading',reference:'SYN-PREVIEW-ASTER',type:'ORGANISATION',email:'aster@example.invalid'},
  {id:'33333333-3333-4333-8333-333333333333',name:'Synthetic Alex Morgan',reference:'SYN-PREVIEW-ALEX',type:'PERSON',email:'alex.morgan@example.invalid'}
];
export const previewCustomers=fixtures.map(f=>({global_party_id:f.id,display_name:f.name,external_reference:f.reference,party_type:f.type,version:1,owner_entity_id:'LE-SG-01'}));
export function previewCustomer(id) {
  const f=fixtures.find(f=>f.id===id);if(!f)return null;
  return {source:{...previewCustomers.find(c=>c.global_party_id===id),source_system:'crm-sg'},view:{global_party_id:id,entity_id:'LE-SG-01',views:[
    {scope_id:f.id,scope_kind:'party',owner_entity_id:'LE-SG-01',store_id:'STORE-SG-01',served_from:'browser-preview',data_version:1,rows:[{table:'party',row:{global_party_id:id,display_name:f.name,party_type:f.type}}]},
    {scope_id:f.id.replace(/.$/,'9'),scope_kind:'relationship',owner_entity_id:'LE-SG-01',store_id:'STORE-SG-01',served_from:'browser-preview',data_version:1,rows:[{table:'relationship',row:{relationship_type:'PERSONAL_BANKING',status:'ACTIVE'}},{table:'contact_info',row:{channel:'EMAIL',value:f.email}},{table:'consent',row:{channel:'EMAIL',purpose:'servicing',status:'GRANTED'}}]}
  ]}};
}
