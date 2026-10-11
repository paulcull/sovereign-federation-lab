// Deployment chooses the mode. A live API failure never enables simulation.
export async function labMode(){
  const response=await fetch('/lab-config.json',{cache:'no-store'});
  if(!response.ok)throw Error('Lab deployment configuration is unavailable.');
  const config=await response.json();
  if(!['live','simulation'].includes(config.mode))throw Error('Invalid lab mode.');
  if(config.mode==='live'&&config.database!=='cockroach')throw Error('Live lab requires CockroachDB.');
  return config.mode;
}
